from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import yaml


PROJECT_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_LOCAL_CONFIG_PATH = PROJECT_DIR / "inventories/templ-local/group_vars/all/main.yml"
PREFIX_PATTERN = re.compile(r"[a-z][a-z0-9-]*")


def lima_node_prefix() -> str:
  with TEMPLATE_LOCAL_CONFIG_PATH.open(encoding="utf-8") as source:
    configuration: Any = yaml.safe_load(source)

  if not isinstance(configuration, dict):
    raise ValueError(f"{TEMPLATE_LOCAL_CONFIG_PATH} must contain a mapping.")

  prefix = configuration.get("lima_node_prefix")
  if not isinstance(prefix, str) or not PREFIX_PATTERN.fullmatch(prefix):
    raise ValueError(
      "lima_node_prefix must be a lowercase DNS-label prefix in "
      f"{TEMPLATE_LOCAL_CONFIG_PATH}."
    )

  return prefix


def main() -> None:
  parser = argparse.ArgumentParser(
    description="Print the three template-local VM names derived from lima_node_prefix."
  )
  parser.add_argument(
    "--shell",
    action="store_true",
    help="print the names as one shell-safe space-separated line",
  )
  arguments = parser.parse_args()

  names = [f"{lima_node_prefix()}-{number}" for number in range(1, 4)]
  print(" ".join(names) if arguments.shell else "\n".join(names))


if __name__ == "__main__":
  main()
