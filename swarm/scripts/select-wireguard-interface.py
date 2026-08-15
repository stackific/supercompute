#!/usr/bin/env python3
"""Select the active WireGuard interface owned by a Docker Swarm config."""

from __future__ import annotations

import argparse
import dataclasses
import sys


@dataclasses.dataclass(frozen=True)
class Interface:
  name: str
  address: str
  public_key: str


def parse_interface(value: str) -> Interface:
  fields = value.split(",", maxsplit=2)
  if len(fields) != 3 or not all(fields):
    raise argparse.ArgumentTypeError("interface must be NAME,ADDRESS,PUBLIC_KEY")
  return Interface(*fields)


def select_interface(
  expected_address: str,
  expected_public_keys: set[str],
  interfaces: list[Interface],
) -> str | None:
  if not expected_public_keys:
    address_owners = [item.name for item in interfaces if item.address == expected_address]
    if address_owners:
      raise ValueError(
        f"{expected_address} is active on {', '.join(address_owners)}, but no "
        "project configuration remains to prove ownership"
      )
    return None

  names = [item.name for item in interfaces]
  if len(names) != len(set(names)):
    raise ValueError("duplicate WireGuard interface names were observed")

  expected_key_owners = [item for item in interfaces if item.public_key in expected_public_keys]
  wrong_address = [item.name for item in expected_key_owners if item.address != expected_address]
  if wrong_address:
    raise ValueError(
      f"the project WireGuard key is active with the wrong address on {', '.join(wrong_address)}"
    )

  address_owners = [item for item in interfaces if item.address == expected_address]
  unknown_address_owners = [
    item.name for item in address_owners if item.public_key not in expected_public_keys
  ]
  if unknown_address_owners:
    raise ValueError(
      f"{expected_address} belongs to an unrelated WireGuard interface: "
      f"{', '.join(unknown_address_owners)}"
    )

  matches = [item.name for item in address_owners if item.public_key in expected_public_keys]
  if len(matches) > 1:
    raise ValueError(f"multiple project-owned interfaces are active: {', '.join(matches)}")
  return matches[0] if matches else None


def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument("--expected-address", required=True)
  parser.add_argument("--expected-public-key", action="append", default=[])
  parser.add_argument("--interface", action="append", default=[], type=parse_interface)
  args = parser.parse_args()

  try:
    selected = select_interface(
      args.expected_address,
      set(args.expected_public_key),
      args.interface,
    )
  except ValueError as error:
    print(f"Cannot safely manage WireGuard: {error}.", file=sys.stderr)
    return 1

  if selected:
    print(selected)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
