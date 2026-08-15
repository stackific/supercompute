#!/usr/bin/env python3
"""Remove only standalone Garage resources carrying recognized ownership labels."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any


MANAGED_LABEL = "com.stackific.docker-swarm.garage-managed"
LEGACY_LABEL = re.compile(
  r"^com\.stackific\.(?P<namespace>[a-z][a-z0-9-]*)\.garage-managed$"
)
STABLE_NAMES = {
  "container": {"swarm-garage"},
  "network": {"swarm-garage"},
  "volume": {"swarm-garage-data", "swarm-garage-metadata"},
}
LEGACY_NAMES = {
  "container": re.compile(r"^(?P<namespace>[a-z][a-z0-9-]*)-garage$"),
  "network": re.compile(r"^(?P<namespace>[a-z][a-z0-9-]*)-garage$"),
  "volume": re.compile(
    r"^(?P<namespace>[a-z][a-z0-9-]*)-garage-(?:data|metadata)$"
  ),
}


class OwnershipError(RuntimeError):
  """A stable Garage name exists without the required ownership label."""


def resource_name(kind: str, resource: dict[str, Any]) -> str:
  name = resource.get("Name", "")
  if kind == "container":
    name = name.removeprefix("/")
  if not isinstance(name, str):
    return ""
  return name


def resource_labels(resource: dict[str, Any]) -> dict[str, str]:
  labels: object
  if "Config" in resource:
    labels = resource.get("Config", {}).get("Labels", {})
  else:
    labels = resource.get("Labels", {})
  return labels if isinstance(labels, dict) else {}


def is_owned(kind: str, resource: dict[str, Any]) -> bool:
  name = resource_name(kind, resource)
  labels = resource_labels(resource)
  if name in STABLE_NAMES[kind]:
    if labels.get(MANAGED_LABEL) != "true":
      raise OwnershipError(
        f"Refusing unmanaged resource using the stable Garage name: {kind} {name}"
      )
    return True

  name_match = LEGACY_NAMES[kind].fullmatch(name)
  if name_match is None:
    return False
  if labels.get(MANAGED_LABEL) == "true":
    return True

  namespace = name_match.group("namespace")
  return any(
    value == "true"
    and (label_match := LEGACY_LABEL.fullmatch(key)) is not None
    and label_match.group("namespace") == namespace
    for key, value in labels.items()
  )


def docker(*arguments: str) -> subprocess.CompletedProcess[str]:
  return subprocess.run(
    ["docker", *arguments],
    check=True,
    capture_output=True,
    text=True,
  )


def inspect_all(kind: str) -> list[dict[str, Any]]:
  list_arguments = [kind, "ls", "--quiet"]
  if kind == "container":
    list_arguments.append("--all")
  identifiers = docker(*list_arguments).stdout.split()
  if not identifiers:
    return []
  inspected = json.loads(docker(kind, "inspect", *identifiers).stdout)
  if not isinstance(inspected, list):
    raise RuntimeError(f"docker {kind} inspect returned an invalid document")
  return inspected


def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument(
    "--check",
    action="store_true",
    help="report recognized resources without removing them",
  )
  arguments = parser.parse_args()
  try:
    resources = {
      kind: [item for item in inspect_all(kind) if is_owned(kind, item)]
      for kind in ("container", "volume", "network")
    }

    changed = any(resources.values())
    if arguments.check:
      for kind, items in resources.items():
        for resource in items:
          print(f"Recognized managed Garage {kind} {resource_name(kind, resource)}.")
      print(f"MATCHED={sum(len(items) for items in resources.values())}")
      print("CHANGED=0")
      return 0

    for resource in resources["container"]:
      name = resource_name("container", resource)
      print(f"Removing managed Garage container {name}.")
      docker("container", "rm", "--force", name)
    for resource in resources["volume"]:
      name = resource_name("volume", resource)
      print(f"Removing managed Garage volume {name}.")
      docker("volume", "rm", name)
    for resource in resources["network"]:
      name = resource_name("network", resource)
      print(f"Removing managed Garage network {name}.")
      docker("network", "rm", name)
    print(f"CHANGED={int(changed)}")
  except subprocess.CalledProcessError as error:
    detail = error.stderr.strip() if error.stderr else str(error)
    print(f"Garage destruction failed: {detail}", file=sys.stderr)
    return 1
  except (OwnershipError, RuntimeError, json.JSONDecodeError) as error:
    print(f"Garage destruction failed: {error}", file=sys.stderr)
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
