#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "deployment.yml"
SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def main() -> None:
  values = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
  name = values.get("deployment_name") if isinstance(values, dict) else None
  if not isinstance(name, str) or not SLUG.fullmatch(name):
    raise ValueError("deployment_name must be a lowercase DNS-label slug")
  print(name)


if __name__ == "__main__":
  main()
