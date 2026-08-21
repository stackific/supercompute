#!/usr/bin/env python3
"""Print the deployment_name from deployment.yml."""

from __future__ import annotations

from pathlib import Path
import re
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
INSTANCE_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def main() -> int:
  path = ROOT / "deployment.yml"
  try:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
  except FileNotFoundError:
    print(f"Deployment configuration does not exist: {path}", file=sys.stderr)
    return 1
  except yaml.YAMLError as error:
    print(f"Deployment configuration is not valid YAML: {error}", file=sys.stderr)
    return 1

  if not isinstance(document, dict):
    print("deployment.yml must contain a YAML mapping", file=sys.stderr)
    return 1
  name = document.get("deployment_name")
  if not isinstance(name, str) or not name.strip():
    print("deployment.yml must contain a non-empty deployment_name", file=sys.stderr)
    return 1
  if Path(name).name != name or name in {".", ".."}:
    print("deployment_name must be a single path-safe name", file=sys.stderr)
    return 1
  if not INSTANCE_NAME.fullmatch(name):
    print("deployment_name must be a lowercase DNS-label name", file=sys.stderr)
    return 1
  print(name)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
