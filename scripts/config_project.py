#!/usr/bin/env python3
"""Print the project id from inventories/<provider>/hosts.yml all.vars."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory_hosts  # noqa: E402


def main() -> int:
  parser = argparse.ArgumentParser(
    description="Print project from inventories/<provider>/hosts.yml all.vars"
  )
  parser.add_argument(
    "--provider",
    default=os.environ.get("ENV", ""),
    help="inventory slug (defaults to ENV environment variable)",
  )
  arguments = parser.parse_args()
  provider = arguments.provider.strip()
  if not provider:
    print(
      "Environment is required (--provider or ENV environment variable).",
      file=sys.stderr,
    )
    return 1
  try:
    print(inventory_hosts.require_project(provider))
  except inventory_hosts.InventoryError as error:
    print(str(error), file=sys.stderr)
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
