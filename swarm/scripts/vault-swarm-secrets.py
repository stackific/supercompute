#!/usr/bin/env python3
"""Ensure Swarm backup and per-node storage secrets in decrypted Vault YAML."""

from __future__ import annotations

import argparse
from pathlib import Path
import secrets
import sys

import yaml


RESTIC_FIELD = "vault_swarm_backup_restic_password"
STORAGE_FIELD = "vault_encryption_at_rest_passphrases"
MINIMUM_SECRET_LENGTH = 32


def load_mapping(path: Path, description: str) -> dict[str, object]:
  document = yaml.safe_load(path.read_text(encoding="utf-8"))
  if not isinstance(document, dict):
    raise ValueError(f"{description} must contain a YAML mapping.")
  return document


def inventory_hosts(path: Path) -> list[str]:
  inventory = load_mapping(path, "Provider inventory")
  try:
    hosts = inventory["all"]["children"]["wireguard_nodes"]["hosts"]
  except (KeyError, TypeError) as error:
    raise ValueError("Provider inventory has no wireguard_nodes host mapping.") from error
  if not isinstance(hosts, dict) or not hosts:
    raise ValueError("Provider inventory must contain at least one WireGuard node.")
  if any(not isinstance(host, str) or not host for host in hosts):
    raise ValueError("Provider inventory contains an invalid WireGuard node name.")
  return list(hosts)


def valid_secret(value: object) -> bool:
  return isinstance(value, str) and len(value) >= MINIMUM_SECRET_LENGTH


def ensure_secrets(vault: dict[str, object], hosts: list[str]) -> bool:
  changed = False
  restic_password = vault.get(RESTIC_FIELD)
  if restic_password is None:
    vault[RESTIC_FIELD] = secrets.token_urlsafe(48)
    changed = True
  elif not valid_secret(restic_password):
    raise ValueError(f"{RESTIC_FIELD} must contain at least 32 characters.")

  storage = vault.get(STORAGE_FIELD)
  if storage is None:
    vault[STORAGE_FIELD] = {host: secrets.token_urlsafe(48) for host in hosts}
    changed = True
  elif not isinstance(storage, dict):
    raise ValueError(f"{STORAGE_FIELD} must be a mapping keyed by inventory node.")
  else:
    if set(storage) != set(hosts):
      raise ValueError(
        f"{STORAGE_FIELD} must contain exactly these nodes: {', '.join(hosts)}."
      )
    for host in hosts:
      if not valid_secret(storage[host]):
        raise ValueError(f"{STORAGE_FIELD}.{host} must contain at least 32 characters.")
  return changed


def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument("--vault", required=True, type=Path)
  parser.add_argument("--inventory", required=True, type=Path)
  arguments = parser.parse_args()

  try:
    vault = load_mapping(arguments.vault, "Decrypted Vault")
    changed = ensure_secrets(vault, inventory_hosts(arguments.inventory))
    if changed:
      arguments.vault.write_text(
        yaml.safe_dump(vault, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
      )
    print("changed" if changed else "verified")
  except (OSError, ValueError, yaml.YAMLError) as error:
    print(str(error), file=sys.stderr)
    return 2
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
