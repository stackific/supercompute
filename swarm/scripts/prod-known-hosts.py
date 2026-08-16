#!/usr/bin/env python3
"""Verify production SSH host keys and atomically render stable known-host aliases."""

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


def validate_endpoint(endpoint: object, node: str) -> str:
  if not isinstance(endpoint, str) or not endpoint:
    raise HostKeyError(f"{node}: prod_wireguard_endpoint must be a non-empty string")
  try:
    address = ipaddress.ip_address(endpoint)
  except ValueError:
    labels = endpoint.rstrip(".").split(".")
    if not labels or any(not DNS_LABEL_PATTERN.fullmatch(label) for label in labels):
      raise HostKeyError(f"{node}: endpoint must be an IPv4 address or DNS hostname")
    return endpoint
  if address.version != 4:
    raise HostKeyError(f"{node}: endpoint must be an IPv4 address or DNS hostname")
  return endpoint


def load_contract(inventory_path: Path) -> list[dict[str, str]]:
  with inventory_path.open(encoding="utf-8") as source:
    inventory = yaml.safe_load(source)
  try:
    hosts = inventory["all"]["children"]["wireguard_nodes"]["hosts"]
  except (KeyError, TypeError) as error:
    raise HostKeyError("Production inventory does not define all.children.wireguard_nodes.hosts") from error
  if not isinstance(hosts, dict) or len(hosts) != 3:
    raise HostKeyError("Production inventory must define exactly three nodes in stable order")
  nodes = tuple(hosts)
  if len(set(nodes)) != 3 or any(not DNS_LABEL_PATTERN.fullmatch(node) for node in nodes):
    raise HostKeyError("Production inventory aliases must be unique DNS labels")

  contract: list[dict[str, str]] = []
  for node in nodes:
    values = hosts[node]
    if not isinstance(values, dict):
      raise HostKeyError(f"{node}: inventory host variables must be a mapping")
    endpoint = validate_endpoint(values.get("prod_wireguard_endpoint"), node)
    fingerprint = values.get("prod_ssh_host_ed25519_sha256")
    if not isinstance(fingerprint, str) or not FINGERPRINT_PATTERN.fullmatch(fingerprint):
      raise HostKeyError(
        f"{node}: prod_ssh_host_ed25519_sha256 must be a complete "
        "console-verified SHA256 fingerprint"
      )
    contract.append({"node": node, "endpoint": endpoint, "expected": fingerprint})

  endpoints = [item["endpoint"] for item in contract]
  if len(set(endpoints)) != len(endpoints):
    raise HostKeyError("Production inventory contains duplicate public endpoints")
  fingerprints = [item["expected"] for item in contract]
  if len(set(fingerprints)) != len(fingerprints):
    raise HostKeyError("Production inventory contains duplicate ED25519 host-key fingerprints")
  return contract


def fingerprint_key_blob(encoded_key: str) -> str:
  try:
    key_blob = base64.b64decode(encoded_key, validate=True)
  except (binascii.Error, ValueError) as error:
    raise HostKeyError("ssh-keyscan returned an invalid ED25519 public-key encoding") from error
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
    raise HostKeyError(f"{node}: endpoint returned no ED25519 host key")
  if len(keys) != 1:
    raise HostKeyError(f"{node}: endpoint returned multiple distinct ED25519 host keys")
  encoded_key, fingerprint = next(iter(keys.items()))
  return encoded_key, fingerprint


def scan_contract(
  contract: list[dict[str, str]],
  timeout: int,
  temporary_directory: Path,
) -> tuple[list[str], list[str]]:
  scanner = shutil.which("ssh-keyscan")
  if scanner is None:
    raise HostKeyError("ssh-keyscan is required on the production controller")

  known_host_lines: list[str] = []
  errors: list[str] = []
  for item in contract:
    node = item["node"]
    endpoint = item["endpoint"]
    expected = item["expected"]
    scan_path = temporary_directory / f"{node}.scan"
    try:
      result = subprocess.run(
        [scanner, "-T", str(timeout), "-t", "ed25519", endpoint],
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
      known_host_lines.append(f"{node} ssh-ed25519 {encoded_key}\n")
      outcome = "match"
    except (HostKeyError, subprocess.TimeoutExpired) as error:
      observed = "<unavailable>"
      if scan_path.exists():
        try:
          _, observed = parse_scan(scan_path.read_text(encoding="utf-8"), node)
        except HostKeyError:
          pass
      errors.append(str(error))
      outcome = "REJECTED"
    print(
      f"node={node} endpoint={endpoint} expected={expected} "
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

  for item, line in zip(contract, lines, strict=True):
    fields = line.split()
    if len(fields) != 3 or fields[0] != item["node"] or fields[1] != "ssh-ed25519":
      raise HostKeyError(
        f"{item['node']}: existing known_hosts entry must be one stable ED25519 alias"
      )
    observed = fingerprint_key_blob(fields[2])
    if observed != item["expected"]:
      raise HostKeyError(f"{item['node']}: existing known_hosts fingerprint mismatch")
    print(
      f"node={item['node']} endpoint={item['endpoint']} expected={item['expected']} "
      f"observed={observed} result=reused"
    )


def main() -> int:
  args = parse_args()
  if args.timeout < 1:
    print("ERROR: --timeout must be at least one second", file=sys.stderr)
    return 2
  try:
    contract = load_contract(args.inventory)
    if args.reuse_existing and args.known_hosts.exists():
      validate_existing_known_hosts(contract, args.known_hosts)
      print(f"CHANGED=0 reused verified mode-0600 {args.known_hosts}")
      return 0
    with tempfile.TemporaryDirectory(prefix="docker-swarm-prod-hostkeys-") as temporary_name:
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
