#!/usr/bin/env python3
"""Sync .state known_hosts aliases from inventories/*/hosts.yml (up)."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import yaml


FINGERPRINT_PATTERN = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
DNS_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
ROOT = Path(__file__).resolve().parents[1]


class HostKeyError(ValueError):
  """An operator-fixable host-key contract error."""


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("--inventory", type=Path, required=True)
  parser.add_argument("--known-hosts", type=Path, required=True)
  parser.add_argument("--timeout", type=int, default=5)
  parser.add_argument(
    "--reuse-existing",
    action="store_true",
    help="reuse a complete mode-0600 alias file after validating every inventory fingerprint",
  )
  return parser.parse_args()


def validate_dial_target(value: object, node: str, field: str) -> str:
  if not isinstance(value, str) or not value:
    raise HostKeyError(f"{node}: {field} must be a non-empty string")
  if value.startswith("REPLACE_WITH_"):
    raise HostKeyError(f"{node}: replace {field} placeholder first")
  try:
    address = ipaddress.ip_address(value)
  except ValueError:
    labels = value.rstrip(".").split(".")
    if not labels or any(not DNS_LABEL_PATTERN.fullmatch(label) for label in labels):
      raise HostKeyError(f"{node}: {field} must be an IPv4 address or DNS hostname")
    return value
  if address.version != 4:
    raise HostKeyError(f"{node}: {field} must be an IPv4 address or DNS hostname")
  return value


def is_roaming(values: dict) -> bool:
  return values.get("wireguard_roaming") is True


def is_lima_guest(values: dict) -> bool:
  return values.get("node_lima_guest") is True


def lima_ssh_ports(inventory_path: Path) -> dict[str, int]:
  """Map lima_nodes[].name → ssh_port from group_vars/all/main.yml."""
  main_path = inventory_path.parent / "group_vars" / "all" / "main.yml"
  try:
    document = yaml.safe_load(main_path.read_text(encoding="utf-8"))
  except FileNotFoundError as error:
    raise HostKeyError(f"Provider configuration does not exist: {main_path}") from error
  except yaml.YAMLError as error:
    raise HostKeyError(f"Invalid YAML in {main_path}: {error}") from error
  if not isinstance(document, dict):
    raise HostKeyError(f"{main_path} must contain a YAML mapping")
  nodes = document.get("lima_nodes", [])
  if nodes is None:
    return {}
  if not isinstance(nodes, list):
    raise HostKeyError("lima_nodes must be a list")
  ports: dict[str, int] = {}
  for entry in nodes:
    if not isinstance(entry, dict):
      raise HostKeyError("lima_nodes entries must be mappings")
    name = entry.get("name")
    port = entry.get("ssh_port")
    if not isinstance(name, str) or not name:
      raise HostKeyError("lima_nodes entry needs a name")
    if not isinstance(port, int) or not 0 < port < 65536:
      raise HostKeyError(f"lima_nodes entry {name} needs an integer ssh_port")
    if name in ports:
      raise HostKeyError(f"lima_nodes declares duplicate name {name}")
    ports[name] = port
  return ports


def inventory_host_vars(inventory: dict) -> dict[str, dict]:
  """Resolve wireguard_nodes members and their host vars (supports children alias)."""
  try:
    children = inventory["all"]["children"]
  except (KeyError, TypeError) as error:
    raise HostKeyError("Inventory must define all.children") from error
  if not isinstance(children, dict):
    raise HostKeyError("all.children must be a mapping")

  wireguard = children.get("wireguard_nodes")
  if not isinstance(wireguard, dict):
    raise HostKeyError("Inventory must define all.children.wireguard_nodes")

  hosts: dict[str, dict] = {}
  direct = wireguard.get("hosts")
  if isinstance(direct, dict):
    for name, values in direct.items():
      hosts[name] = values if isinstance(values, dict) else {}

  nested = wireguard.get("children")
  if isinstance(nested, dict):
    for child_name in nested:
      child = children.get(child_name)
      if not isinstance(child, dict):
        raise HostKeyError(f"wireguard_nodes child group {child_name} is missing")
      child_hosts = child.get("hosts")
      if not isinstance(child_hosts, dict):
        raise HostKeyError(f"Group {child_name} must define hosts")
      for name, values in child_hosts.items():
        hosts[name] = values if isinstance(values, dict) else {}

  if not hosts:
    raise HostKeyError("wireguard_nodes declares no hosts")
  return hosts


def load_contract(inventory_path: Path) -> list[dict[str, str]]:
  """Build the known_hosts sync contract from hosts.yml (source of truth)."""
  with inventory_path.open(encoding="utf-8") as source:
    inventory = yaml.safe_load(source)
  if not isinstance(inventory, dict):
    raise HostKeyError("Inventory must be a YAML mapping")

  hosts = inventory_host_vars(inventory)
  nodes = sorted(hosts)
  if any(not DNS_LABEL_PATTERN.fullmatch(node) for node in nodes):
    raise HostKeyError("Inventory aliases must be DNS labels")
  if len(set(nodes)) != len(nodes):
    raise HostKeyError("Inventory aliases must be unique")

  lima_ports = lima_ssh_ports(inventory_path)
  contract: list[dict[str, str]] = []
  for node in nodes:
    values = hosts[node]
    fingerprint = values.get("cloud_ssh_host_ed25519_sha256")
    if not isinstance(fingerprint, str) or not FINGERPRINT_PATTERN.fullmatch(fingerprint):
      raise HostKeyError(
        f"{node}: cloud_ssh_host_ed25519_sha256 must be a complete "
        "console-verified SHA256 fingerprint"
      )
    if fingerprint.startswith("SHA256:REPLACE_WITH_"):
      raise HostKeyError(f"{node}: replace cloud_ssh_host_ed25519_sha256 placeholder first")

    if is_lima_guest(values):
      if not is_roaming(values):
        raise HostKeyError(f"{node}: node_lima_guest requires wireguard_roaming: true")
      if values.get("cloud_bootstrap_ssh_host"):
        raise HostKeyError(
          f"{node}: node_lima_guest must omit cloud_bootstrap_ssh_host "
          "(bootstrap uses Lima-local SSH)"
        )
      if values.get("cloud_wireguard_endpoint"):
        raise HostKeyError(
          f"{node}: node_lima_guest must omit cloud_wireguard_endpoint"
        )
      if node not in lima_ports:
        raise HostKeyError(f"{node}: node_lima_guest requires a matching lima_nodes entry")
      dial = "127.0.0.1"
      kind = "lima"
      port = str(lima_ports[node])
    elif is_roaming(values):
      dial = validate_dial_target(
        values.get("cloud_bootstrap_ssh_host"),
        node,
        "cloud_bootstrap_ssh_host",
      )
      kind = "roaming"
      port = ""
    else:
      dial = validate_dial_target(
        values.get("cloud_wireguard_endpoint"),
        node,
        "cloud_wireguard_endpoint",
      )
      kind = "public"
      port = ""

    contract.append(
      {
        "node": node,
        "endpoint": dial,
        "port": port,
        "expected": fingerprint,
        "kind": kind,
      }
    )

  public_endpoints = [item["endpoint"] for item in contract if item["kind"] == "public"]
  if len(set(public_endpoints)) != len(public_endpoints):
    raise HostKeyError("Inventory contains duplicate public endpoints among static hosts")
  roaming_hosts = [item["endpoint"] for item in contract if item["kind"] == "roaming"]
  if len(set(roaming_hosts)) != len(roaming_hosts):
    raise HostKeyError("Inventory contains duplicate cloud_bootstrap_ssh_host values")
  lima_endpoints = [
    f"{item['endpoint']}:{item['port']}" for item in contract if item["kind"] == "lima"
  ]
  if len(set(lima_endpoints)) != len(lima_endpoints):
    raise HostKeyError("Inventory contains duplicate Lima SSH dial targets")
  fingerprints = [item["expected"] for item in contract]
  if len(set(fingerprints)) != len(fingerprints):
    raise HostKeyError("Inventory contains duplicate ED25519 host-key fingerprints")
  return contract


def fingerprint_key_blob(encoded_key: str) -> str:
  try:
    key_blob = base64.b64decode(encoded_key, validate=True)
  except (binascii.Error, ValueError) as error:
    raise HostKeyError("invalid ED25519 public-key encoding") from error
  digest = base64.b64encode(hashlib.sha256(key_blob).digest()).decode("ascii").rstrip("=")
  return f"SHA256:{digest}"


def parse_scan(scan_output: str, node: str) -> tuple[str, str]:
  keys: dict[str, str] = {}
  wrong_types: set[str] = set()
  for raw_line in scan_output.splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
      continue
    fields = line.split()
    if len(fields) < 3:
      raise HostKeyError(f"{node}: ssh-keyscan returned a malformed host-key line")
    key_type = fields[1]
    if key_type != "ssh-ed25519":
      wrong_types.add(key_type)
      continue
    keys[fields[2]] = fingerprint_key_blob(fields[2])
  if wrong_types:
    types = ", ".join(sorted(wrong_types))
    raise HostKeyError(f"{node}: ssh-keyscan returned wrong key type(s): {types}")
  if not keys:
    raise HostKeyError(f"{node}: dial target returned no ED25519 host key")
  if len(keys) != 1:
    raise HostKeyError(f"{node}: dial target returned multiple distinct ED25519 host keys")
  encoded_key, fingerprint = next(iter(keys.items()))
  return encoded_key, fingerprint


def parse_host_pubkey_line(output: str, node: str) -> tuple[str, str]:
  for raw_line in output.splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
      continue
    fields = line.split()
    if len(fields) < 2:
      continue
    if fields[0] != "ssh-ed25519":
      continue
    return fields[1], fingerprint_key_blob(fields[1])
  raise HostKeyError(
    f"{node}: bootstrap SSH did not return /etc/ssh/ssh_host_ed25519_key.pub "
    "(prove `ssh <cloud_bootstrap_ssh_host> true` per internal/roaming-nodes.md first)"
  )


def scan_public_node(
  node: str,
  endpoint: str,
  expected: str,
  timeout: int,
  temporary_directory: Path,
  *,
  port: int | None = None,
) -> tuple[str, str]:
  scanner = shutil.which("ssh-keyscan")
  if scanner is None:
    raise HostKeyError("ssh-keyscan is required on the production controller")
  scan_path = temporary_directory / f"{node}.scan"
  argv = [scanner, "-T", str(timeout), "-t", "ed25519"]
  if port is not None:
    argv.extend(["-p", str(port)])
  argv.append(endpoint)
  result = subprocess.run(
    argv,
    check=False,
    capture_output=True,
    text=True,
    timeout=timeout + 2,
  )
  scan_path.write_text(result.stdout, encoding="utf-8")
  scan_path.chmod(0o600)
  encoded_key, observed = parse_scan(result.stdout, node)
  if result.returncode != 0:
    raise HostKeyError(f"{node}: ssh-keyscan failed with exit code {result.returncode}")
  if observed != expected:
    raise HostKeyError(f"{node}: ED25519 host-key fingerprint mismatch")
  return encoded_key, observed


def scan_roaming_node(
  node: str,
  bootstrap_host: str,
  expected: str,
  timeout: int,
) -> tuple[str, str]:
  """Fetch the origin host key through the operator SSH config (Cloudflare ProxyCommand)."""
  result = subprocess.run(
    [
      "ssh",
      "-o",
      "BatchMode=yes",
      "-o",
      f"ConnectTimeout={timeout}",
      "-o",
      "StrictHostKeyChecking=no",
      "-o",
      "UserKnownHostsFile=/dev/null",
      "-o",
      "GlobalKnownHostsFile=/dev/null",
      bootstrap_host,
      "cat /etc/ssh/ssh_host_ed25519_key.pub",
    ],
    check=False,
    capture_output=True,
    text=True,
    timeout=timeout + 15,
  )
  if result.returncode != 0:
    detail = (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}"
    raise HostKeyError(
      f"{node}: bootstrap SSH to {bootstrap_host} failed ({detail}). "
      "Prove SSH via Cloudflare first (internal/roaming-nodes.md), then re-run up."
    )
  encoded_key, observed = parse_host_pubkey_line(result.stdout, node)
  if observed != expected:
    raise HostKeyError(f"{node}: ED25519 host-key fingerprint mismatch")
  return encoded_key, observed


def scan_contract(
  contract: list[dict[str, str]],
  timeout: int,
  temporary_directory: Path,
) -> tuple[list[str], list[str]]:
  known_host_lines: list[str] = []
  errors: list[str] = []
  for item in contract:
    node = item["node"]
    endpoint = item["endpoint"]
    expected = item["expected"]
    kind = item["kind"]
    try:
      if kind == "roaming":
        encoded_key, observed = scan_roaming_node(node, endpoint, expected, timeout)
      elif kind == "lima":
        port = int(item["port"])
        encoded_key, observed = scan_public_node(
          node,
          endpoint,
          expected,
          timeout,
          temporary_directory,
          port=port,
        )
      else:
        encoded_key, observed = scan_public_node(
          node, endpoint, expected, timeout, temporary_directory
        )
      known_host_lines.append(f"{node} ssh-ed25519 {encoded_key}\n")
      outcome = "match"
    except (HostKeyError, subprocess.TimeoutExpired, ValueError) as error:
      observed = "<unavailable>"
      errors.append(str(error))
      outcome = "REJECTED"
    endpoint_display = (
      f"{endpoint}:{item['port']}" if kind == "lima" and item.get("port") else endpoint
    )
    print(
      f"node={node} kind={kind} endpoint={endpoint_display} expected={expected} "
      f"observed={observed} result={outcome}"
    )
  return known_host_lines, errors


def install_known_hosts(known_hosts_path: Path, content: str) -> bool:
  encoded_content = content.encode("utf-8")
  if known_hosts_path.exists():
    existing_content = known_hosts_path.read_bytes()
    existing_mode = known_hosts_path.stat().st_mode & 0o777
    if existing_content == encoded_content and existing_mode == 0o600:
      return False

  known_hosts_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
  known_hosts_path.parent.chmod(0o700)
  file_descriptor, temporary_name = tempfile.mkstemp(
    prefix=f".{known_hosts_path.name}.",
    dir=known_hosts_path.parent,
  )
  temporary_path = Path(temporary_name)
  try:
    os.fchmod(file_descriptor, 0o600)
    with os.fdopen(file_descriptor, "wb") as destination:
      destination.write(encoded_content)
      destination.flush()
      os.fsync(destination.fileno())
    os.replace(temporary_path, known_hosts_path)
  finally:
    if temporary_path.exists():
      temporary_path.unlink()
  return True


def validate_existing_known_hosts(
  contract: list[dict[str, str]],
  known_hosts_path: Path,
) -> None:
  if known_hosts_path.is_symlink() or not known_hosts_path.is_file():
    raise HostKeyError(f"{known_hosts_path} must be a regular file")
  if known_hosts_path.stat().st_mode & 0o777 != 0o600:
    raise HostKeyError(f"{known_hosts_path} must have mode 0600")

  lines = known_hosts_path.read_text(encoding="utf-8").splitlines()
  if len(lines) != len(contract):
    raise HostKeyError(
      f"{known_hosts_path} must contain exactly one ED25519 alias for each production node"
    )

  by_alias = {}
  for line in lines:
    fields = line.split()
    if len(fields) != 3 or fields[1] != "ssh-ed25519":
      raise HostKeyError("existing known_hosts entries must be stable ED25519 aliases")
    by_alias[fields[0]] = fields[2]

  expected_aliases = {item["node"] for item in contract}
  if set(by_alias) != expected_aliases:
    raise HostKeyError(
      f"{known_hosts_path} aliases {sorted(by_alias)} do not match inventory "
      f"{sorted(expected_aliases)}"
    )

  for item in contract:
    encoded = by_alias[item["node"]]
    observed = fingerprint_key_blob(encoded)
    if observed != item["expected"]:
      raise HostKeyError(f"{item['node']}: existing known_hosts fingerprint mismatch")
    endpoint_display = (
      f"{item['endpoint']}:{item['port']}"
      if item["kind"] == "lima" and item.get("port")
      else item["endpoint"]
    )
    print(
      f"node={item['node']} kind={item['kind']} endpoint={endpoint_display} "
      f"expected={item['expected']} observed={observed} result=reused"
    )


def main() -> int:
  args = parse_args()
  if args.timeout < 1:
    print("ERROR: --timeout must be at least one second", file=sys.stderr)
    return 2
  try:
    contract = load_contract(args.inventory)
    if args.reuse_existing and args.known_hosts.exists():
      try:
        validate_existing_known_hosts(contract, args.known_hosts)
        print(f"CHANGED=0 reused verified mode-0600 {args.known_hosts}")
        return 0
      except HostKeyError as error:
        # Inventory add/remove (alias set or line count) → rewrite .state from hosts.yml.
        message = str(error)
        stale_alias_set = (
          "must contain exactly one ED25519 alias" in message
          or "do not match inventory" in message
          or "missing from existing known_hosts" in message
        )
        if not stale_alias_set:
          raise
        print(
          f"Existing known_hosts is stale for current inventory ({error}); "
          "rescanning dial targets from hosts.yml."
        )
    prefix = f"{ROOT.name}-prod-hostkeys-"
    with tempfile.TemporaryDirectory(prefix=prefix) as temporary_name:
      temporary_directory = Path(temporary_name)
      temporary_directory.chmod(0o700)
      known_host_lines, errors = scan_contract(contract, args.timeout, temporary_directory)
    if errors:
      print("ERROR: Production SSH host-key bootstrap rejected:", file=sys.stderr)
      for error in errors:
        print(f"  - {error}", file=sys.stderr)
      print("Existing known_hosts state was preserved.", file=sys.stderr)
      return 1
    changed = install_known_hosts(args.known_hosts, "".join(known_host_lines))
  except (HostKeyError, OSError, yaml.YAMLError) as error:
    print(f"ERROR: {error}", file=sys.stderr)
    print("Existing known_hosts state was preserved.", file=sys.stderr)
    return 1

  if changed:
    print(f"CHANGED=1 atomically installed mode-0600 {args.known_hosts}")
  else:
    print(f"CHANGED=0 verified existing mode-0600 {args.known_hosts}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
