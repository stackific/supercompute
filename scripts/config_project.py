#!/usr/bin/env python3
"""Print the project id from config.yml."""

from __future__ import annotations

from pathlib import Path
import re
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
INSTANCE_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def main() -> int:
  path = ROOT / "config.yml"
  try:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
  except FileNotFoundError:
    print(f"Cloud configuration does not exist: {path}", file=sys.stderr)
    return 1
  except yaml.YAMLError as error:
    print(f"Cloud configuration is not valid YAML: {error}", file=sys.stderr)
    return 1

  if not isinstance(document, dict):
    print("config.yml must contain a YAML mapping", file=sys.stderr)
    return 1
  project = document.get("project")
  if not isinstance(project, str) or not project.strip():
    print("config.yml must contain a non-empty project", file=sys.stderr)
    return 1
  if Path(project).name != project or project in {".", ".."}:
    print("project must be a single path-safe name", file=sys.stderr)
    return 1
  if not INSTANCE_NAME.fullmatch(project):
    print("project must be a lowercase DNS-label name", file=sys.stderr)
    return 1
  print(project)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
