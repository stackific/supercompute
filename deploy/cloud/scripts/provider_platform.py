#!/usr/bin/env python3
"""Print provider.platform from inventories/<provider>/group_vars/all/main.yml."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
  parser = argparse.ArgumentParser(description="Print a provider platform")
  parser.add_argument("--provider", required=True)
  arguments = parser.parse_args()

  path = ROOT / "inventories" / arguments.provider / "group_vars" / "all" / "main.yml"
  try:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
  except FileNotFoundError:
    print(f"Provider configuration does not exist: {path}", file=sys.stderr)
    return 1
  except yaml.YAMLError as error:
    print(f"Invalid YAML in {path}: {error}", file=sys.stderr)
    return 1

  if not isinstance(document, dict):
    print(f"{path} must contain a YAML mapping", file=sys.stderr)
    return 1
  provider = document.get("provider")
  if not isinstance(provider, dict):
    print(f"{path} must contain a provider mapping", file=sys.stderr)
    return 1
  platform = provider.get("platform")
  if not isinstance(platform, str) or not platform.strip():
    print(f"{path} must define provider.platform", file=sys.stderr)
    return 1
  print(platform)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
