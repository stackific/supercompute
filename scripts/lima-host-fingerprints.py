#!/usr/bin/env python3
"""Capture Lima guest SSH host ED25519 fingerprints into hosts.yml after lima-up."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml


FINGERPRINT_PATTERN = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
HOST_KEY_LINE = re.compile(
  r"^(\s*prod_ssh_host_ed25519_sha256:\s*)(?P<q>[\"']?)(?P<value>[^\"'#\n]+)(?P=q)(\s*(?:#.*)?)?$"
)
ROOT = Path(__file__).resolve().parents[1]


class FingerprintError(ValueError):
  """An operator-fixable Lima host-key capture error."""


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(
    description=(
      "Discover ED25519 SHA256 host-key fingerprints for node_lima_guest hosts "
      "and write them into inventories/<provider>/hosts.yml"
    )
  )
  parser.add_argument("--provider", required=True)
  parser.add_argument("--timeout", type=int, default=5)
  parser.add_argument("--retries", type=int, default=30)
  parser.add_argument("--retry-delay", type=float, default=1.0)
  parser.add_argument(
    "--force",
    action="store_true",
    help="overwrite a complete inventory fingerprint that differs from the guest",
  )
  return parser.parse_args()


def inventory_paths(provider: str) -> tuple[Path, Path]:
  inventory_dir = ROOT / "inventories" / provider
  hosts_path = inventory_dir / "hosts.yml"
  main_path = inventory_dir / "group_vars" / "all" / "main.yml"
  if not hosts_path.is_file():
    raise FingerprintError(f"Provider inventory does not exist: {hosts_path}")
  if not main_path.is_file():
    raise FingerprintError(f"Provider configuration does not exist: {main_path}")
  return hosts_path, main_path


def deployment_hosts(document: dict) -> dict[str, dict]:
  try:
    children = document["all"]["children"]
  except (KeyError, TypeError) as error:
    raise FingerprintError("Inventory must define all.children") from error
  if not isinstance(children, dict):
    raise FingerprintError("all.children must be a mapping")
  deployment = children.get("deployment")
  if not isinstance(deployment, dict):
    raise FingerprintError("Inventory must define all.children.deployment")
  hosts = deployment.get("hosts")
  if hosts is None:
    return {}
  if not isinstance(hosts, dict):
    raise FingerprintError("deployment.hosts must be a mapping")
  resolved: dict[str, dict] = {}
  for name, values in hosts.items():
    if values is None:
      resolved[name] = {}
    elif isinstance(values, dict):
      resolved[name] = values
    else:
      raise FingerprintError(f"deployment host {name} must map to a YAML mapping")
  return resolved


def lima_ssh_ports(main_path: Path) -> dict[str, int]:
  try:
    document = yaml.safe_load(main_path.read_text(encoding="utf-8"))
  except yaml.YAMLError as error:
    raise FingerprintError(f"Invalid YAML in {main_path}: {error}") from error
  if not isinstance(document, dict):
    raise FingerprintError(f"{main_path} must contain a YAML mapping")
  nodes = document.get("lima_nodes", [])
  if nodes is None:
    return {}
  if not isinstance(nodes, list):
    raise FingerprintError("lima_nodes must be a list")
  ports: dict[str, int] = {}
  for entry in nodes:
    if not isinstance(entry, dict):
      raise FingerprintError("lima_nodes entries must be mappings")
    name = entry.get("name")
    port = entry.get("ssh_port")
    if not isinstance(name, str) or not name:
      raise FingerprintError("lima_nodes entry needs a name")
    if not isinstance(port, int) or not 0 < port < 65536:
      raise FingerprintError(f"lima_nodes entry {name} needs an integer ssh_port")
    if name in ports:
      raise FingerprintError(f"lima_nodes declares duplicate name {name}")
    ports[name] = port
  return ports


def fingerprint_key_blob(encoded_key: str) -> str:
  try:
    key_blob = base64.b64decode(encoded_key, validate=True)
  except (binascii.Error, ValueError) as error:
    raise FingerprintError("invalid ED25519 public-key encoding") from error
  digest = base64.b64encode(hashlib.sha256(key_blob).digest()).decode("ascii").rstrip("=")
  return f"SHA256:{digest}"


def parse_scan(scan_output: str, node: str) -> str:
  keys: dict[str, str] = {}
  wrong_types: set[str] = set()
  for raw_line in scan_output.splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
      continue
    fields = line.split()
    if len(fields) < 3:
      raise FingerprintError(f"{node}: ssh-keyscan returned a malformed host-key line")
    key_type = fields[1]
    if key_type != "ssh-ed25519":
      wrong_types.add(key_type)
      continue
    keys[fields[2]] = fingerprint_key_blob(fields[2])
  if wrong_types:
    types = ", ".join(sorted(wrong_types))
    raise FingerprintError(f"{node}: ssh-keyscan returned wrong key type(s): {types}")
  if not keys:
    raise FingerprintError(f"{node}: Lima dial target returned no ED25519 host key")
  if len(keys) != 1:
    raise FingerprintError(
      f"{node}: Lima dial target returned multiple distinct ED25519 host keys"
    )
  return next(iter(keys.values()))


def scan_lima_fingerprint(node: str, port: int, timeout: int) -> str:
  scanner = shutil.which("ssh-keyscan")
  if scanner is None:
    raise FingerprintError("ssh-keyscan is required on the controller")
  result = subprocess.run(
    [scanner, "-T", str(timeout), "-t", "ed25519", "-p", str(port), "127.0.0.1"],
    check=False,
    capture_output=True,
    text=True,
    timeout=timeout + 2,
  )
  if result.returncode != 0 and not result.stdout.strip():
    detail = (result.stderr or "").strip() or f"exit {result.returncode}"
    raise FingerprintError(f"{node}: ssh-keyscan 127.0.0.1:{port} failed ({detail})")
  return parse_scan(result.stdout, node)


def scan_with_retries(
  node: str,
  port: int,
  timeout: int,
  retries: int,
  retry_delay: float,
) -> str:
  attempts = max(1, retries)
  last_error: Exception | None = None
  for attempt in range(1, attempts + 1):
    try:
      return scan_lima_fingerprint(node, port, timeout)
    except (FingerprintError, subprocess.TimeoutExpired) as error:
      last_error = error
      if attempt == attempts:
        break
      time.sleep(retry_delay)
  assert last_error is not None
  raise FingerprintError(f"{node}: failed after {attempts} attempt(s): {last_error}") from last_error


def is_placeholder_fingerprint(value: object) -> bool:
  if not isinstance(value, str) or not value:
    return True
  if "REPLACE_WITH_" in value:
    return True
  return not FINGERPRINT_PATTERN.fullmatch(value)


def load_lima_guest_targets(
  hosts_path: Path,
  main_path: Path,
) -> list[dict[str, object]]:
  try:
    document = yaml.safe_load(hosts_path.read_text(encoding="utf-8"))
  except yaml.YAMLError as error:
    raise FingerprintError(f"Invalid YAML in {hosts_path}: {error}") from error
  if not isinstance(document, dict):
    raise FingerprintError("Inventory must be a YAML mapping")

  hosts = deployment_hosts(document)
  ports = lima_ssh_ports(main_path)
  guests = sorted(
    name for name, values in hosts.items() if values.get("node_lima_guest") is True
  )
  if not guests:
    return []

  targets: list[dict[str, object]] = []
  for node in guests:
    values = hosts[node]
    if values.get("wireguard_roaming") is not True:
      raise FingerprintError(f"{node}: node_lima_guest requires wireguard_roaming: true")
    if values.get("prod_bootstrap_ssh_host"):
      raise FingerprintError(
        f"{node}: node_lima_guest must omit prod_bootstrap_ssh_host "
        "(bootstrap uses Lima-local SSH)"
      )
    if values.get("prod_wireguard_endpoint"):
      raise FingerprintError(f"{node}: node_lima_guest must omit prod_wireguard_endpoint")
    if node not in ports:
      raise FingerprintError(f"{node}: node_lima_guest requires a matching lima_nodes entry")
    if "prod_ssh_host_ed25519_sha256" not in values:
      raise FingerprintError(
        f"{node}: hosts.yml must declare prod_ssh_host_ed25519_sha256 "
        "(placeholder OK before lima-up)"
      )
    targets.append(
      {
        "node": node,
        "port": ports[node],
        "current": values.get("prod_ssh_host_ed25519_sha256"),
      }
    )

  guest_set = set(guests)
  orphan_ports = sorted(set(ports) - guest_set)
  if orphan_ports:
    raise FingerprintError(
      "lima_nodes names must exactly match node_lima_guest hosts; "
      f"extra lima_nodes entries: {', '.join(orphan_ports)}"
    )
  return targets


def replace_host_fingerprint(text: str, node: str, fingerprint: str) -> str:
  lines = text.splitlines(keepends=True)
  host_header = re.compile(rf"^(\s+){re.escape(node)}:\s*(?:#.*)?$")
  host_indent: str | None = None
  in_host = False
  replaced = False
  found_host = False
  output: list[str] = []

  for line in lines:
    if not in_host:
      match = host_header.match(line)
      if match:
        host_indent = match.group(1)
        in_host = True
        found_host = True
      output.append(line)
      continue

    assert host_indent is not None
    still_in_host = (not line.strip()) or line.startswith(host_indent + " ") or line.startswith(
      host_indent + "\t"
    )
    if not still_in_host:
      if not replaced:
        raise FingerprintError(
          f"{node}: could not find prod_ssh_host_ed25519_sha256 under the host block"
        )
      in_host = False
      host_indent = None
      output.append(line)
      continue

    key_match = HOST_KEY_LINE.match(line.rstrip("\n"))
    if key_match and not replaced:
      newline = "\n" if line.endswith("\n") else ""
      comment = key_match.group(4) or ""
      output.append(f'{key_match.group(1)}"{fingerprint}"{comment}{newline}')
      replaced = True
      continue

    output.append(line)

  if not found_host:
    raise FingerprintError(f"{node}: host block not found in hosts.yml")
  if not replaced:
    raise FingerprintError(
      f"{node}: could not find prod_ssh_host_ed25519_sha256 under the host block"
    )
  return "".join(output)


def install_hosts_yml(hosts_path: Path, content: str) -> bool:
  encoded = content.encode("utf-8")
  if hosts_path.exists() and hosts_path.read_bytes() == encoded:
    return False
  file_descriptor, temporary_name = tempfile.mkstemp(
    prefix=f".{hosts_path.name}.",
    dir=hosts_path.parent,
  )
  temporary_path = Path(temporary_name)
  try:
    mode = hosts_path.stat().st_mode & 0o777 if hosts_path.exists() else 0o644
    os.fchmod(file_descriptor, mode)
    with os.fdopen(file_descriptor, "wb") as destination:
      destination.write(encoded)
      destination.flush()
      os.fsync(destination.fileno())
    os.replace(temporary_path, hosts_path)
  finally:
    if temporary_path.exists():
      temporary_path.unlink()
  return True


def main() -> int:
  args = parse_args()
  if args.timeout < 1:
    print("ERROR: --timeout must be at least one second", file=sys.stderr)
    return 2
  if args.retries < 1:
    print("ERROR: --retries must be at least one", file=sys.stderr)
    return 2
  if args.retry_delay < 0:
    print("ERROR: --retry-delay must be non-negative", file=sys.stderr)
    return 2

  try:
    hosts_path, main_path = inventory_paths(args.provider)
    targets = load_lima_guest_targets(hosts_path, main_path)
    if not targets:
      print(f"No node_lima_guest hosts in {hosts_path}; nothing to do.")
      return 0

    updates: dict[str, str] = {}
    for item in targets:
      node = str(item["node"])
      port = int(item["port"])
      current = item["current"]
      observed = scan_with_retries(
        node, port, args.timeout, args.retries, args.retry_delay
      )
      if not FINGERPRINT_PATTERN.fullmatch(observed):
        raise FingerprintError(f"{node}: observed fingerprint is not a complete SHA256 value")

      if isinstance(current, str) and current == observed:
        print(f"node={node} port={port} fingerprint={observed} result=unchanged")
        continue

      if not is_placeholder_fingerprint(current) and not args.force:
        raise FingerprintError(
          f"{node}: inventory fingerprint {current} differs from guest {observed}; "
          "re-run with --force after confirming the guest was recreated"
        )

      updates[node] = observed
      prior = current if isinstance(current, str) else "<missing>"
      print(
        f"node={node} port={port} fingerprint={observed} "
        f"prior={prior} result=update"
      )

    if not updates:
      print(f"CHANGED=0 verified Lima guest fingerprints in {hosts_path}")
      return 0

    text = hosts_path.read_text(encoding="utf-8")
    for node, fingerprint in updates.items():
      text = replace_host_fingerprint(text, node, fingerprint)
    changed = install_hosts_yml(hosts_path, text)
  except (FingerprintError, OSError, yaml.YAMLError) as error:
    print(f"ERROR: {error}", file=sys.stderr)
    return 1

  if changed:
    print(f"CHANGED=1 wrote Lima guest fingerprints into {hosts_path}")
  else:
    print(f"CHANGED=0 verified Lima guest fingerprints in {hosts_path}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
