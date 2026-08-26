#!/usr/bin/env python3
"""Resolve non-secret production SSH settings from inventory files."""

from __future__ import annotations

import os
from pathlib import Path
import re
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
HOME_LOOKUP = re.compile(
  r"\{\{\s*lookup\(\s*['\"](?:ansible\.builtin\.)?env['\"]\s*,\s*['\"]HOME['\"]\s*\)\s*\}\}"
)
PROJECT_VAR = re.compile(r"\{\{\s*project\s*\}\}")
INVENTORY_SLUG_VAR = re.compile(r"\{\{\s*inventory_slug\s*\}\}")


def read_mapping(path: Path) -> dict:
  document = yaml.safe_load(path.read_text(encoding="utf-8"))
  if not isinstance(document, dict):
    raise ValueError(f"{path.relative_to(ROOT)} must contain a YAML mapping.")
  return document


def config_project() -> str:
  document = read_mapping(ROOT / "config.yml")
  project = document.get("project")
  if not isinstance(project, str) or not project.strip():
    raise ValueError("config.yml must contain a non-empty project")
  if Path(project).name != project or project in {".", ".."} or not SLUG.fullmatch(project):
    raise ValueError("project must be a lowercase DNS-label name")
  return project


def scalar(value: object, description: str) -> str:
  if isinstance(value, str) and value and not any(character.isspace() for character in value):
    return value
  if isinstance(value, int) and value > 0:
    return str(value)
  raise ValueError(f"{description} must be a non-empty, whitespace-free scalar.")


def wireguard_host_vars(hosts_document: dict) -> dict[str, dict]:
  children = hosts_document.get("all", {}).get("children", {})
  if not isinstance(children, dict):
    raise ValueError("hosts.yml is missing all.children")
  wireguard = children.get("wireguard_nodes")
  if not isinstance(wireguard, dict):
    raise ValueError("hosts.yml is missing all.children.wireguard_nodes")

  result: dict[str, dict] = {}
  direct = wireguard.get("hosts")
  if isinstance(direct, dict):
    for name, values in direct.items():
      result[name] = values if isinstance(values, dict) else {}
  nested = wireguard.get("children")
  if isinstance(nested, dict):
    for child_name in nested:
      child = children.get(child_name)
      if not isinstance(child, dict):
        raise ValueError(f"wireguard_nodes child group {child_name} is missing")
      child_hosts = child.get("hosts")
      if not isinstance(child_hosts, dict):
        raise ValueError(f"Group {child_name} must define hosts")
      for name, values in child_hosts.items():
        result[name] = values if isinstance(values, dict) else {}
  return result


def resolve_private_key_file(
  value: object,
  *,
  inventory_slug: str,
) -> str:
  """Expand the supported Ansible path form used in group_vars for wg-ssh."""
  if value is None:
    return ""
  if not isinstance(value, str) or not value.strip():
    raise ValueError("ssh_private_key_file must be a non-empty string when set")

  home = os.environ.get("HOME", "")
  if not home:
    raise ValueError("HOME must be set to resolve ssh_private_key_file")

  resolved = HOME_LOOKUP.sub(home, value)
  resolved = PROJECT_VAR.sub(config_project(), resolved)
  resolved = INVENTORY_SLUG_VAR.sub(inventory_slug, resolved)
  if "{{" in resolved or "{%" in resolved:
    raise ValueError(
      "ssh_private_key_file contains unsupported Jinja; use "
      "{{ lookup('ansible.builtin.env', 'HOME') }}/.ssh/"
      "{{ project }}-{{ inventory_slug }} or an absolute path"
    )
  path = Path(resolved).expanduser()
  if not path.is_absolute():
    raise ValueError(f"ssh_private_key_file must resolve to an absolute path: {path}")
  return str(path)


def resolve(inventory_slug: str, node: str) -> tuple[str, str, str, str]:
  if not SLUG.fullmatch(inventory_slug):
    raise ValueError("inventory slug must be a lowercase DNS-label slug")
  inventory = ROOT / "inventories" / inventory_slug
  main = read_mapping(inventory / "group_vars/all/main.yml")
  hosts = read_mapping(inventory / "hosts.yml")

  manager_hosts = wireguard_host_vars(hosts)
  if node not in manager_hosts:
    raise ValueError(f"{node} is not a production WireGuard node in hosts.yml.")

  overrides = manager_hosts[node]
  address = scalar(
    overrides.get("wireguard_address"),
    f"{node}.wireguard_address",
  )
  lima_guest = overrides.get("node_lima_guest") is True
  if lima_guest:
    user = os.environ.get("USER", "").strip()
    if not user:
      raise ValueError("USER must be set for Lima guest mesh SSH (matches lima_guest_user)")
    port = scalar(main.get("default_ssh_port", 22), "SSH port")
    lima_home = os.environ.get("LIMA_HOME", "")
    if not lima_home:
      home = os.environ.get("HOME", "")
      if not home:
        raise ValueError("HOME must be set to resolve the Lima SSH identity")
      lima_home = str(Path(home) / ".lima" / f".{config_project()}-{inventory_slug}")
    private_key = str(Path(lima_home) / "_config" / "user")
  else:
    user = scalar(
      overrides.get("ansible_user", main.get("default_ssh_user")),
      "SSH user",
    )
    if user.startswith("REPLACE_WITH_"):
      raise ValueError("Replace default_ssh_user placeholder first.")
    port = scalar(
      overrides.get("ansible_port", main.get("default_ssh_port")),
      "SSH port",
    )
    private_key = resolve_private_key_file(
      main.get("ssh_private_key_file"),
      inventory_slug=inventory_slug,
    )
  if not port.isdecimal() or not 0 < int(port) < 65536:
    raise ValueError("SSH port must be an integer between 1 and 65535.")
  return address, user, port, private_key


def main() -> int:
  if len(sys.argv) != 3:
    print(f"Usage: {Path(sys.argv[0]).name} INVENTORY_SLUG NODE", file=sys.stderr)
    return 2
  try:
    print("\t".join(resolve(sys.argv[1], sys.argv[2])))
  except ValueError as error:
    print(f"Production SSH configuration error: {error}", file=sys.stderr)
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
