#!/usr/bin/env python3
"""Resolve non-secret production SSH settings from inventory files."""

from __future__ import annotations

import sys
from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def read_mapping(path: Path) -> dict:
  document = yaml.safe_load(path.read_text(encoding="utf-8"))
  if not isinstance(document, dict):
    raise ValueError(f"{path.relative_to(ROOT)} must contain a YAML mapping.")
  return document


def scalar(value: object, description: str) -> str:
  if isinstance(value, str) and value and not any(character.isspace() for character in value):
    return value
  if isinstance(value, int) and value > 0:
    return str(value)
  raise ValueError(f"{description} must be a non-empty, whitespace-free scalar.")


def wireguard_host_vars(hosts_document: dict) -> dict[str, dict]:
  children = hosts_document.get("all", {}).get("children", {})
  if not isinstance(children, dict):
    raise ValueError("hosts.yml is missing all.children")
  wireguard = children.get("wireguard_nodes")
  if not isinstance(wireguard, dict):
    raise ValueError("hosts.yml is missing all.children.wireguard_nodes")

  result: dict[str, dict] = {}
  direct = wireguard.get("hosts")
  if isinstance(direct, dict):
    for name, values in direct.items():
      result[name] = values if isinstance(values, dict) else {}
  nested = wireguard.get("children")
  if isinstance(nested, dict):
    for child_name in nested:
      child = children.get(child_name)
      if not isinstance(child, dict):
        raise ValueError(f"wireguard_nodes child group {child_name} is missing")
      child_hosts = child.get("hosts")
      if not isinstance(child_hosts, dict):
        raise ValueError(f"Group {child_name} must define hosts")
      for name, values in child_hosts.items():
        result[name] = values if isinstance(values, dict) else {}
  return result


def resolve(inventory_slug: str, node: str) -> tuple[str, str, str]:
  if not SLUG.fullmatch(inventory_slug):
    raise ValueError("inventory slug must be a lowercase DNS-label slug")
  inventory = ROOT / "inventories" / inventory_slug
  main = read_mapping(inventory / "group_vars/all/main.yml")
  hosts = read_mapping(inventory / "hosts.yml")

  addresses = main.get("prod_wireguard_node_addresses")
  if not isinstance(addresses, dict) or node not in addresses:
    raise ValueError(f"{node} is not in prod_wireguard_node_addresses.")

  manager_hosts = wireguard_host_vars(hosts)
  if node not in manager_hosts:
    raise ValueError(f"{node} is not a production WireGuard node in hosts.yml.")

  overrides = manager_hosts[node]
  address = scalar(addresses[node], f"prod_wireguard_node_addresses.{node}")
  user = scalar(
    overrides.get("ansible_user", main.get("prod_default_ssh_user")),
    "SSH user",
  )
  if user.startswith("REPLACE_WITH_"):
    raise ValueError("Replace prod_default_ssh_user placeholder first.")
  port = scalar(
    overrides.get("ansible_port", main.get("prod_default_ssh_port")),
    "SSH port",
  )
  if not port.isdecimal() or not 0 < int(port) < 65536:
    raise ValueError("SSH port must be an integer between 1 and 65535.")
  return address, user, port


def main() -> int:
  if len(sys.argv) != 3:
    print(f"Usage: {Path(sys.argv[0]).name} INVENTORY_SLUG NODE", file=sys.stderr)
    return 2
  try:
    print("\t".join(resolve(sys.argv[1], sys.argv[2])))
  except ValueError as error:
    print(f"Production SSH configuration error: {error}", file=sys.stderr)
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
