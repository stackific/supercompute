"""Read operator inventory from inventories/<provider>/hosts.yml and group_vars."""

from __future__ import annotations

from pathlib import Path
import re
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
PROJECT_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
DNS_PREFIX_KEYS = (
  "dns_prefix_ns",
  "dns_prefix_api",
  "dns_prefix_app",
  "dns_prefix_apps",
)


class InventoryError(ValueError):
  """An operator-fixable inventory contract error."""


def hosts_path(provider: str) -> Path:
  return ROOT / "inventories" / provider / "hosts.yml"


def _load_yaml_mapping(path: Path) -> dict:
  try:
    text = path.read_text(encoding="utf-8")
  except FileNotFoundError as error:
    raise InventoryError(f"Provider inventory does not exist: {path}") from error
  if text.lstrip().startswith("$ANSIBLE_VAULT"):
    return {}
  try:
    document = yaml.safe_load(text)
  except yaml.YAMLError as error:
    raise InventoryError(f"Invalid YAML in {path}: {error}") from error
  if document is None:
    return {}
  if not isinstance(document, dict):
    raise InventoryError(f"{path} must contain a YAML mapping")
  return document


def load_document(provider: str) -> dict:
  path = hosts_path(provider)
  document = _load_yaml_mapping(path)
  if not document:
    raise InventoryError(f"{path} must contain a YAML mapping")
  return document


def load_group_vars_all(provider: str) -> dict:
  """Load group_vars/all/*.yml (skip the encrypted vault)."""
  merged: dict = {}
  all_dir = ROOT / "inventories" / provider / "group_vars" / "all"
  if all_dir.is_dir():
    for path in sorted(all_dir.glob("*.yml")):
      if path.name == "vault.yml":
        continue
      merged.update(_load_yaml_mapping(path))
  return merged


def all_vars(document: dict) -> dict:
  all_block = document.get("all")
  if not isinstance(all_block, dict):
    return {}
  values = all_block.get("vars")
  if not isinstance(values, dict):
    return {}
  return values


def _hosts_from_nodes_group(nodes_group: dict, *, sibling_groups: dict) -> dict[str, dict]:
  hosts: dict[str, dict] = {}
  direct = nodes_group.get("hosts")
  if isinstance(direct, dict):
    for name, values in direct.items():
      hosts[name] = values if isinstance(values, dict) else {}

  nested = nodes_group.get("children")
  if isinstance(nested, dict):
    for child_name in nested:
      child = sibling_groups.get(child_name)
      if not isinstance(child, dict):
        raise InventoryError(f"nodes child group {child_name} is missing")
      child_hosts = child.get("hosts")
      if not isinstance(child_hosts, dict):
        raise InventoryError(f"Group {child_name} must define hosts")
      for name, values in child_hosts.items():
        hosts[name] = values if isinstance(values, dict) else {}
  return hosts


def node_hosts(document: dict) -> dict[str, dict]:
  """Resolve nodes members and their host vars."""
  top_level_nodes = document.get("nodes")
  if isinstance(top_level_nodes, dict):
    hosts = _hosts_from_nodes_group(top_level_nodes, sibling_groups=document)
    if hosts:
      return hosts

  try:
    children = document["all"]["children"]
  except (KeyError, TypeError) as error:
    raise InventoryError("hosts.yml must define nodes.hosts") from error
  if not isinstance(children, dict):
    raise InventoryError("all.children must be a mapping")

  nodes_group = children.get("nodes")
  if not isinstance(nodes_group, dict):
    raise InventoryError("hosts.yml must define nodes.hosts")

  hosts = _hosts_from_nodes_group(nodes_group, sibling_groups=children)
  if not hosts:
    raise InventoryError("nodes declares no hosts")
  return hosts


def require_scalar(values: dict, key: str, *, path: str) -> str:
  value = values.get(key)
  if not isinstance(value, str) or not value.strip():
    raise InventoryError(f"{path} must define a non-empty {key}")
  return value.strip()


def validate_project(project: str, *, path: str) -> str:
  if Path(project).name != project or project in {".", ".."}:
    raise InventoryError(f"{path}: project must be a single path-safe name")
  if not PROJECT_PATTERN.fullmatch(project):
    raise InventoryError(f"{path}: project must be a lowercase DNS-label name")
  return project


def dns_prefixes(provider: str) -> dict[str, str]:
  values = load_group_vars_all(provider)
  path = f"inventories/{provider}/group_vars/all/main.yml"
  return {key: require_scalar(values, key, path=path) for key in DNS_PREFIX_KEYS}


def derived_dns_names(hostname: str, prefixes: dict[str, str]) -> dict[str, str]:
  return {
    "nameserver_hostname": f"{prefixes['dns_prefix_ns']}.{hostname}",
    "sc_api": f"{prefixes['dns_prefix_api']}.{hostname}",
    "sc_app": f"{prefixes['dns_prefix_app']}.{hostname}",
    "sc_apps": f"{prefixes['dns_prefix_apps']}.{hostname}",
  }


def validate_hostname(hostname: str, *, path: str) -> str:
  if "REPLACE_WITH_" in hostname or "<" in hostname or ">" in hostname:
    raise InventoryError(
      f"{path}: set hostname to your cloud DNS name (for example example.com)"
    )
  if "." not in hostname:
    raise InventoryError(f"{path}: hostname must be a DNS name with a dot")
  return hostname


def identity_vars(provider: str, *, document: dict | None = None) -> dict[str, str]:
  document = document if document is not None else load_document(provider)
  values = all_vars(document)
  path = f"inventories/{provider}/hosts.yml all.vars"
  project = validate_project(require_scalar(values, "project", path=path), path=path)
  hostname = validate_hostname(require_scalar(values, "hostname", path=path), path=path)
  return {
    "project": project,
    "hostname": hostname,
    **derived_dns_names(hostname, dns_prefixes(provider)),
  }


def require_project(provider: str) -> str:
  return identity_vars(provider)["project"]


def deployment_vars(provider: str, *, document: dict | None = None) -> dict[str, str]:
  return identity_vars(provider, document=document)


def validate_deployment_config(provider: str) -> None:
  """Validate hosts.yml settings required before task up."""
  identity_vars(provider)


def launchd_label(provider: str) -> str:
  identity = identity_vars(provider)
  reverse_dns = ".".join(reversed(identity["hostname"].split(".")))
  return f"{reverse_dns}.{identity['project']}.{provider}.wireguard"


def provider_from_environment() -> str:
  provider = __import__("os").environ.get("ENV", "")
  if not provider:
    raise InventoryError("ENV must name an inventories/<slug>/hosts.yml entry")
  if not hosts_path(provider).is_file():
    raise InventoryError(f"Provider inventory does not exist: {hosts_path(provider)}")
  return provider
