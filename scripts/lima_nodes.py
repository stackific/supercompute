#!/usr/bin/env python3
"""Print inventory hosts marked node_lima_guest for a provider."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory_hosts  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
INSTANCE_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def lima_guest_hosts(provider: str) -> list[str]:
  try:
    hosts = inventory_hosts.node_hosts(inventory_hosts.load_document(provider))
  except inventory_hosts.InventoryError as error:
    raise ValueError(str(error)) from error

  names = sorted(
    name
    for name, values in hosts.items()
    if values.get("node_lima_guest") is True
  )
  for name in names:
    if not INSTANCE_NAME.fullmatch(name):
      raise ValueError(f"Invalid Lima guest inventory host name: {name}")
  return names


def main() -> int:
  parser = argparse.ArgumentParser(
    description="Print node_lima_guest host names from inventories/<provider>/hosts.yml"
  )
  parser.add_argument("--provider", required=True)
  arguments = parser.parse_args()
  try:
    names = lima_guest_hosts(arguments.provider)
  except ValueError as error:
    print(str(error), file=sys.stderr)
    return 1
  print("\n".join(names))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
