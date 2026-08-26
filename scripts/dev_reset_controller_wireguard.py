#!/usr/bin/env python3
"""Disconnect the controller WireGuard interface during dev-reset."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
LAUNCHD_DIR = Path("/Library/LaunchDaemons")
WIREGUARD_RUNTIME_DIR = Path("/var/run/wireguard")


class ResetError(RuntimeError):
  pass


def run(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
  result = subprocess.run(
    arguments,
    check=False,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
  )
  if check and result.returncode != 0:
    detail = result.stderr.strip() or result.stdout.strip() or "command failed"
    raise ResetError(f"{' '.join(arguments)}: {detail}")
  return result


def load_main(provider: str) -> dict:
  path = ROOT / "inventories" / provider / "group_vars" / "all" / "main.yml"
  try:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
  except FileNotFoundError as error:
    raise ResetError(f"Provider configuration does not exist: {path}") from error
  except yaml.YAMLError as error:
    raise ResetError(f"Invalid YAML in {path}: {error}") from error
  if not isinstance(document, dict):
    raise ResetError(f"{path} must contain a YAML mapping")
  return document


def launchd_path(provider: str) -> Path:
  config_path = ROOT / "config.yml"
  try:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
  except FileNotFoundError as error:
    raise ResetError(f"Cloud configuration does not exist: {config_path}") from error
  except yaml.YAMLError as error:
    raise ResetError(f"Cloud configuration is not valid YAML: {error}") from error
  if not isinstance(config, dict):
    raise ResetError("config.yml must contain a YAML mapping")
  hostname = config.get("hostname")
  project = config.get("project")
  if not isinstance(hostname, str) or not hostname.strip():
    raise ResetError("config.yml must contain a non-empty hostname")
  if not isinstance(project, str) or not project.strip():
    raise ResetError("config.yml must contain a non-empty project")
  reverse_dns = ".".join(reversed(hostname.split(".")))
  label = f"{reverse_dns}.{project}.{provider}.wireguard"
  return LAUNCHD_DIR / f"{label}.plist"


def tracked_config_path(provider: str, interface: str) -> Path:
  return ROOT / ".state" / provider / "wireguard" / f"{interface}.conf"


def read_plist(path: Path) -> dict:
  result = run("plutil", "-convert", "json", "-o", "-", str(path), check=False)
  if result.returncode != 0:
    return {}
  try:
    document = json.loads(result.stdout)
  except json.JSONDecodeError:
    return {}
  return document if isinstance(document, dict) else {}


def plist_label(path: Path) -> str:
  label = read_plist(path).get("Label")
  return label if isinstance(label, str) else path.stem


def plist_config_path(path: Path) -> Path | None:
  document = read_plist(path)
  arguments = document.get("ProgramArguments")
  if not isinstance(arguments, list) or len(arguments) < 3:
    return None
  config = arguments[2]
  if not isinstance(config, str) or not config.strip():
    return None
  return Path(config)


def address_active(address: str) -> bool:
  result = run("ifconfig", check=True)
  for line in result.stdout.splitlines():
    stripped = line.strip()
    if stripped.startswith("inet ") and stripped.split()[1] == address:
      return True
  return False


def interface_has_address(interface: str, address: str) -> bool:
  result = run("ifconfig", interface, check=False)
  if result.returncode != 0:
    return False
  for line in result.stdout.splitlines():
    stripped = line.strip()
    if stripped.startswith("inet ") and stripped.split()[1] == address:
      return True
  return False


def find_interface_for_address(address: str) -> str | None:
  result = run("ifconfig", check=True)
  current: str | None = None
  for line in result.stdout.splitlines():
    if line and not line.startswith(("\t", " ")):
      current = line.split(":", maxsplit=1)[0]
      continue
    if current is None:
      continue
    stripped = line.strip()
    if stripped.startswith("inet ") and stripped.split()[1] == address:
      return current
  return None


def launchd_loaded(label: str) -> bool:
  return run("launchctl", "print", f"system/{label}", check=False).returncode == 0


def unload_launchd(path: Path) -> None:
  if not path.is_file():
    return
  label = plist_label(path)
  if not launchd_loaded(label):
    return
  result = run("launchctl", "bootout", "system", str(path), check=False)
  if result.returncode != 0 and "No such process" not in (result.stderr or ""):
    raise ResetError(result.stderr.strip() or f"launchctl bootout failed for {label}")


def wg_quick_down(config: Path) -> None:
  if not config.is_file():
    return
  wg_quick = run("which", "wg-quick", check=True).stdout.strip()
  run(wg_quick, "down", str(config), check=False)


def config_declares_address(config: Path, address: str) -> bool:
  if not config.is_file():
    return False
  try:
    content = config.read_text(encoding="utf-8")
  except OSError:
    return False
  for line in content.splitlines():
    stripped = line.strip()
    if stripped.startswith("Address") and address in stripped:
      return True
  return False


def project_runtime_pair(logical_interface: str) -> tuple[str, str] | None:
  name_path = WIREGUARD_RUNTIME_DIR / f"{logical_interface}.name"
  if not name_path.is_file():
    return None
  try:
    real = name_path.read_text(encoding="utf-8").strip()
  except OSError:
    return None
  if not real:
    return None
  return logical_interface, real


def delete_routes_for_interface(interface: str) -> None:
  result = run("netstat", "-nr", "-f", "inet", check=True)
  destinations: list[str] = []
  for line in result.stdout.splitlines():
    parts = line.split()
    if len(parts) >= 6 and parts[-2] == interface:
      destinations.append(parts[0])
  for destination in destinations:
    run("route", "-q", "-n", "delete", "-inet", destination, check=False)


def teardown_wireguard_runtime(logical: str, real: str) -> None:
  if not real.startswith("utun"):
    raise ResetError(f"refusing to tear down non-utun WireGuard runtime interface {real}")
  delete_routes_for_interface(real)
  socket_path = WIREGUARD_RUNTIME_DIR / f"{real}.sock"
  name_path = WIREGUARD_RUNTIME_DIR / f"{logical}.name"
  if socket_path.exists():
    socket_path.unlink()
  if name_path.exists():
    name_path.unlink()


def teardown_project_runtime(address: str, logical_interface: str) -> None:
  pair = project_runtime_pair(logical_interface)
  if pair is not None:
    logical, real = pair
    if interface_has_address(real, address) or find_interface_for_address(address) == real:
      teardown_wireguard_runtime(logical, real)
      return

  active_interface = find_interface_for_address(address)
  if active_interface is None:
    return

  raise ResetError(
    f"{address} is active on {active_interface}, but "
    f"/var/run/wireguard/{logical_interface}.name is missing. "
    "Remove the orphan controller WireGuard state manually, then rerun dev-reset."
  )


def wait_for_address_inactive(address: str, seconds: int = 10) -> bool:
  for _ in range(seconds):
    if not address_active(address):
      return True
    time.sleep(1)
  return not address_active(address)


def disconnect_orphan_controller(provider: str) -> None:
  main = load_main(provider)
  address = main.get("wireguard_controller_address")
  interface = main.get("wireguard_interface")
  if not isinstance(address, str) or not address.strip():
    raise ResetError("wireguard_controller_address must be a non-empty string")
  if not isinstance(interface, str) or not interface.strip():
    raise ResetError("wireguard_interface must be a non-empty string")

  tracked_config = tracked_config_path(provider, interface)
  launchd = launchd_path(provider)
  config_paths: list[Path] = []

  if tracked_config.is_file():
    config_paths.append(tracked_config)

  unload_launchd(launchd)
  plist_config = plist_config_path(launchd)
  if plist_config is not None:
    config_paths.append(plist_config)

  seen: set[str] = set()
  for config in config_paths:
    key = str(config)
    if key in seen:
      continue
    seen.add(key)
    if config.is_file() and (
      config == tracked_config or config_declares_address(config, address)
    ):
      wg_quick_down(config)

  if address_active(address):
    teardown_project_runtime(address, interface)

  if not wait_for_address_inactive(address):
    raise ResetError(
      f"{address} is still active after dev-reset controller WireGuard cleanup"
    )

  if not tracked_config.is_file() and launchd.is_file():
    launchd.unlink(missing_ok=True)


def provider_from_environment() -> str:
  provider = os.environ.get("PROVIDER", "").strip()
  if not provider:
    raise ResetError("PROVIDER must be set")
  return provider


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--provider", default="")
  return parser.parse_args()


def main() -> int:
  arguments = parse_args()
  provider = arguments.provider.strip() or provider_from_environment()
  expected_confirm = f"reset-{provider}"
  if os.environ.get("CONFIRM") != expected_confirm:
    print(f"error: CONFIRM must be exactly {expected_confirm}", file=sys.stderr)
    return 1
  try:
    disconnect_orphan_controller(provider)
  except ResetError as error:
    print(f"error: {error}", file=sys.stderr)
    return 1
  print(f"Controller WireGuard disconnected for provider {provider}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
