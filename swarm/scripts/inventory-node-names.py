#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def nodes(inventory_slug: str) -> list[str]:
  if not SLUG.fullmatch(inventory_slug):
    raise ValueError("inventory slug must be a lowercase DNS-label slug")
  path = ROOT / "inventories" / inventory_slug / "hosts.yml"
  values = yaml.safe_load(path.read_text(encoding="utf-8"))
  try:
    hosts = values["all"]["children"]["wireguard_nodes"]["hosts"]
  except (KeyError, TypeError) as error:
    raise ValueError(f"{path.relative_to(ROOT)} must define wireguard_nodes.hosts") from error
  names = list(hosts) if isinstance(hosts, dict) else []
  if len(names) != 3 or len(set(names)) != 3 or any(not SLUG.fullmatch(name) for name in names):
    raise ValueError("wireguard_nodes.hosts must contain exactly three unique DNS-label aliases")
  return names


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("inventory_slug")
  arguments = parser.parse_args()
  print(" ".join(nodes(arguments.inventory_slug)))


if __name__ == "__main__":
  main()
