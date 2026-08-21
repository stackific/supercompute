#!/usr/bin/env python3
"""Print deployment-group Lima VM names for a provider inventory."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
INSTANCE_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def provider_hosts(provider: str) -> list[str]:
  path = ROOT / "inventories" / provider / "hosts.yml"
  try:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
  except FileNotFoundError as error:
    raise ValueError(f"Provider inventory does not exist: {path}") from error
  except yaml.YAMLError as error:
    raise ValueError(f"Invalid YAML in {path}: {error}") from error

  if not isinstance(document, dict):
    raise ValueError("hosts.yml must contain a YAML mapping")
  children = document.get("all")
  if not isinstance(children, dict):
    raise ValueError("hosts.yml must contain an all mapping")
  groups = children.get("children")
  if not isinstance(groups, dict):
    raise ValueError("hosts.yml must contain all.children")
  deployment = groups.get("deployment")
  if not isinstance(deployment, dict):
    raise ValueError("hosts.yml must contain all.children.deployment")
  hosts = deployment.get("hosts")
  if hosts is None:
    return []
  if not isinstance(hosts, dict):
    raise ValueError("deployment.hosts must be a mapping")

  names = sorted(hosts)
  for name in names:
    if not INSTANCE_NAME.fullmatch(name):
      raise ValueError(f"Invalid Lima VM inventory host name: {name}")
  return names


def main() -> int:
  parser = argparse.ArgumentParser(
    description="Print Lima VM names from inventories/<provider>/hosts.yml"
  )
  parser.add_argument("--provider", required=True)
  arguments = parser.parse_args()
  try:
    names = provider_hosts(arguments.provider)
  except ValueError as error:
    print(str(error), file=sys.stderr)
    return 1
  print("\n".join(names))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
