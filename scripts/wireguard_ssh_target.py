#!/usr/bin/env python3
"""Resolve WireGuard SSH target details for a Lima provider node."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_yaml(path: Path) -> dict:
  try:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
  except FileNotFoundError as error:
    raise ValueError(f"Missing file: {path}") from error
  except yaml.YAMLError as error:
    raise ValueError(f"Invalid YAML in {path}: {error}") from error
  if not isinstance(document, dict):
    raise ValueError(f"{path} must contain a YAML mapping")
  return document


def lima_runtime_home(provider: str) -> Path:
  deployment = load_yaml(ROOT / "config.yml")
  name = deployment.get("project")
  if not isinstance(name, str) or not name.strip():
    raise ValueError("config.yml must contain project")
  home = Path.home() / ".lima" / f".{name}-{provider}"
  return home


def main() -> int:
  parser = argparse.ArgumentParser(description="Resolve wg-ssh target fields")
  parser.add_argument("--provider", required=True)
  parser.add_argument("--node", required=True)
  arguments = parser.parse_args()

  try:
    group_vars = load_yaml(
      ROOT / "inventories" / arguments.provider / "group_vars" / "all" / "main.yml"
    )
    nodes = group_vars.get("lima_nodes")
    if not isinstance(nodes, list) or not nodes:
      raise ValueError("lima_nodes must be a non-empty list")

    match = None
    for node in nodes:
      if isinstance(node, dict) and node.get("name") == arguments.node:
        match = node
        break
    if match is None:
      names = ", ".join(
        str(node.get("name")) for node in nodes if isinstance(node, dict)
      )
      raise ValueError(f"NODE must be one of: {names}")

    address = match.get("wg_address")
    if not isinstance(address, str) or not address:
      raise ValueError(f"lima_nodes entry {arguments.node} needs wg_address")

    macos_address = group_vars.get("wireguard_macos_address")
    if not isinstance(macos_address, str) or not macos_address:
      raise ValueError("wireguard_macos_address is required")

    guest_user = os.environ.get("USER")
    if not guest_user:
      raise ValueError("USER must be set")

    lima_home = lima_runtime_home(arguments.provider)
    state_dir = ROOT / ".state" / arguments.provider / "wireguard"
    print(
      "\t".join(
        [
          address,
          guest_user,
          macos_address,
          str(lima_home),
          str(state_dir / "wg.conf"),
          str(state_dir / "known_hosts"),
          str(lima_home / "_config" / "user"),
        ]
      )
    )
  except ValueError as error:
    print(str(error), file=sys.stderr)
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
