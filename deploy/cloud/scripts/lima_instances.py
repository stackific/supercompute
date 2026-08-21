#!/usr/bin/env python3
"""Inspect Lima instances in LIMA_HOME as JSON or a status table."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any


INSTANCE_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def run(*arguments: str) -> subprocess.CompletedProcess[str]:
  return subprocess.run(
    ["limactl", *arguments],
    check=False,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
  )


def format_gib(value: int | None) -> str:
  if value is None:
    return "-"
  gib = value / (1024**3)
  if abs(gib - round(gib)) < 0.05:
    return f"{int(round(gib))}GiB"
  return f"{gib:.1f}GiB"


def guest_usage(name: str) -> tuple[int | None, int | None]:
  # MemAvailable from /proc, and free bytes summed across every mounted
  # partition of the root virtual disk (matches limactl's Disk size).
  result = run(
    "shell",
    name,
    "--",
    "sh",
    "-c",
    r"""
awk '/MemAvailable:/ {print $2 * 1024}' /proc/meminfo
root_src=$(findmnt -n -o SOURCE /)
root_disk=$(lsblk -n -o PKNAME "$root_src" 2>/dev/null | head -1)
if [ -n "$root_disk" ] && [ -b "/dev/$root_disk" ]; then
  lsblk -b -n -o FSAVAIL,TYPE,MOUNTPOINT "/dev/$root_disk" |
    awk '$2 == "part" && $3 != "" { sum += $1 } END { print sum + 0 }'
else
  df -B1 -P -l -x tmpfs -x devtmpfs -x squashfs |
    awk 'NR > 1 { sum += $4 } END { print sum + 0 }'
fi
""",
  )
  if result.returncode != 0:
    return None, None
  lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
  if len(lines) != 2:
    return None, None
  try:
    return int(lines[0]), int(lines[1])
  except ValueError:
    return None, None


def inspect_instances(*, with_usage: bool) -> dict[str, Any]:
  if not os.environ.get("LIMA_HOME"):
    raise RuntimeError("LIMA_HOME is required")

  quiet = run("list", "--quiet")
  if quiet.returncode != 0:
    raise RuntimeError("limactl could not enumerate instances")

  names = [line.strip() for line in quiet.stdout.splitlines() if line.strip()]
  for name in names:
    if not INSTANCE_NAME.fullmatch(name):
      raise RuntimeError(f"unsafe instance name: {name}")

  instances: dict[str, dict[str, Any]] = {}
  states: dict[str, str] = {}
  if names:
    detail = run("list", "--format", "json", "--all-fields", *names)
    if detail.returncode != 0:
      raise RuntimeError("limactl could not inspect instances")
    for line in detail.stdout.splitlines():
      if not line.strip():
        continue
      item = json.loads(line)
      if not isinstance(item, dict):
        raise RuntimeError("limactl returned an invalid instance record")
      name = item.get("name")
      status = item.get("status", "Unknown")
      if not isinstance(name, str) or not INSTANCE_NAME.fullmatch(name):
        raise RuntimeError(f"unsafe instance name: {name!r}")
      if not isinstance(status, str):
        raise RuntimeError(f"invalid status for {name}")
      cpus = item.get("cpus")
      memory = item.get("memory")
      disk = item.get("disk")
      if not isinstance(cpus, int) or cpus < 1:
        raise RuntimeError(f"invalid cpus for {name}")
      if not isinstance(memory, int) or memory < 1:
        raise RuntimeError(f"invalid memory for {name}")
      if not isinstance(disk, int) or disk < 1:
        raise RuntimeError(f"invalid disk for {name}")

      memory_available = None
      disk_available = None
      if with_usage and status == "Running":
        memory_available, disk_available = guest_usage(name)

      states[name] = status
      instances[name] = {
        "status": status,
        "cpus": cpus,
        "memory_bytes": memory,
        "disk_bytes": disk,
        "memory_available_bytes": memory_available,
        "disk_available_bytes": disk_available,
      }

    if sorted(instances) != sorted(names):
      raise RuntimeError("limactl name and detail enumerations disagree")

  return {
    "all_names": sorted(names),
    "states": states,
    "instances": instances,
  }


def render_table(
  snapshot: dict[str, Any],
  inventory_hosts: list[str],
) -> str:
  headers = [
    "NAME",
    "STATUS",
    "CPUS",
    "MEMORY",
    "DISK",
    "RAM_FREE",
    "DISK_FREE",
    "OWNER",
  ]
  rows: list[list[str]] = []
  inventory = set(inventory_hosts)
  names = sorted(set(snapshot["all_names"]) | inventory)
  instances = snapshot.get("instances", {})

  for name in names:
    record = instances.get(name)
    if record is None:
      rows.append([name, "Absent", "-", "-", "-", "-", "-", "inventory"])
      continue
    owner = "inventory" if name in inventory else "foreign"
    rows.append(
      [
        name,
        str(record["status"]),
        str(record["cpus"]),
        format_gib(record["memory_bytes"]),
        format_gib(record["disk_bytes"]),
        format_gib(record.get("memory_available_bytes")),
        format_gib(record.get("disk_available_bytes")),
        owner,
      ]
    )

  widths = [len(header) for header in headers]
  for row in rows:
    for index, cell in enumerate(row):
      widths[index] = max(widths[index], len(cell))

  def fmt(row: list[str]) -> str:
    return "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row))

  lines = [fmt(headers), fmt(["-" * width for width in widths])]
  lines.extend(fmt(row) for row in rows)
  if not rows:
    lines.append("(no Lima instances)")
  return "\n".join(lines)


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
    "--usage",
    action="store_true",
    help="probe running guests for free RAM and free disk",
  )
  parser.add_argument(
    "--table",
    action="store_true",
    help="print a human-readable status table instead of JSON",
  )
  parser.add_argument(
    "--inventory-hosts",
    default="",
    help="comma-separated inventory host names to include in the table",
  )
  arguments = parser.parse_args()
  inventory_hosts = [
    name.strip()
    for name in arguments.inventory_hosts.split(",")
    if name.strip()
  ]
  try:
    snapshot = inspect_instances(with_usage=arguments.usage or arguments.table)
    if arguments.table:
      print(render_table(snapshot, inventory_hosts))
    else:
      print(json.dumps(snapshot, separators=(",", ":"), sort_keys=True))
  except RuntimeError as error:
    print(str(error), file=sys.stderr)
    return 1
  except json.JSONDecodeError as error:
    print(f"limactl returned invalid JSON: {error}", file=sys.stderr)
    return 1
  return 0

if __name__ == "__main__":
  raise SystemExit(main())
