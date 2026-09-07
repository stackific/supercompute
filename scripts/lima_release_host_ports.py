#!/usr/bin/env python3
"""Release inventory Lima WireGuard host UDP ports held by limactl."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import time


def run(*arguments: str) -> subprocess.CompletedProcess[str]:
  return subprocess.run(
    arguments,
    check=False,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
  )


def limactl_pids_for_udp_port(port: int) -> list[int]:
  result = run("lsof", "-nP", "-t", f"-iUDP:{port}", "-c", "limactl")
  if result.returncode not in {0, 1}:
    detail = result.stderr.strip() or "lsof failed"
    raise RuntimeError(f"could not inspect UDP/{port}: {detail}")

  pids: list[int] = []
  for line in result.stdout.splitlines():
    line = line.strip()
    if not line:
      continue
    try:
      pids.append(int(line))
    except ValueError as error:
      raise RuntimeError(f"unexpected lsof pid line for UDP/{port}: {line!r}") from error
  return sorted(set(pids))


def hostagent_pids_for_instance(name: str) -> list[int]:
  pattern = f"limactl hostagent .* {name}"
  result = run("pgrep", "-f", pattern)
  if result.returncode not in {0, 1}:
    detail = result.stderr.strip() or "pgrep failed"
    raise RuntimeError(f"could not inspect hostagent for {name}: {detail}")

  pids: list[int] = []
  for line in result.stdout.splitlines():
    line = line.strip()
    if not line:
      continue
    try:
      pids.append(int(line))
    except ValueError as error:
      raise RuntimeError(f"unexpected pgrep pid line for {name}: {line!r}") from error
  return sorted(set(pids))


def terminate_pids(pids: list[int]) -> None:
  for pid in pids:
    try:
      os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
      continue

  if not pids:
    return

  time.sleep(1)

  for pid in pids:
    try:
      os.kill(pid, 0)
    except ProcessLookupError:
      continue
    try:
      os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
      continue


def parse_ports(raw_ports: str) -> list[int]:
  ports: list[int] = []
  for item in raw_ports.split(","):
    item = item.strip()
    if not item:
      continue
    port = int(item)
    if not 0 < port < 65536:
      raise ValueError(f"invalid UDP port: {port}")
    ports.append(port)
  if not ports:
    raise ValueError("at least one UDP port is required")
  return ports


def parse_names(raw_names: str) -> list[str]:
  names = [item.strip() for item in raw_names.split(",") if item.strip()]
  return names


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
    "--ports",
    required=True,
    help="comma-separated inventory host_port values",
  )
  parser.add_argument(
    "--instance-names",
    default="",
    help="comma-separated Lima instance names for hostagent cleanup",
  )
  arguments = parser.parse_args()

  ports = parse_ports(arguments.ports)
  names = parse_names(arguments.instance_names)

  pid_sets = [set(limactl_pids_for_udp_port(port)) for port in ports]
  for name in names:
    pid_sets.append(set(hostagent_pids_for_instance(name)))

  pids = sorted(set().union(*pid_sets)) if pid_sets else []
  terminate_pids(pids)

  busy_ports = [port for port in ports if limactl_pids_for_udp_port(port)]
  if busy_ports:
    formatted = ", ".join(str(port) for port in busy_ports)
    print(f"error: limactl still holds inventory UDP port(s): {formatted}", flush=True)
    return 1

  return 0


if __name__ == "__main__":
  raise SystemExit(main())
