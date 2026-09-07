#!/usr/bin/env python3
"""Validate hosts.yml deployment settings required before task up."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory_hosts  # noqa: E402
import vault as provider_vault  # noqa: E402


def main() -> int:
  try:
    provider = inventory_hosts.provider_from_environment()
    inventory_hosts.validate_deployment_config(provider)
    provider_vault.validate_deployment_vault(provider)
  except (inventory_hosts.InventoryError, provider_vault.VaultError) as error:
    print(f"error: {error}", file=sys.stderr)
    return 1
  print(f"Deployment config valid for {provider}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
