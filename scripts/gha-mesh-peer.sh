#!/usr/bin/env bash
# Ephemeral WireGuard peer for GitHub Actions runners (control_plane=gha).
# Keys never appear on argv; values are masked in Actions logs when possible.
set -Eeuo pipefail

usage() {
  echo "Usage: $0 PROVIDER present|absent" >&2
  exit 2
}

mask_value() {
  local value="$1"
  if [[ -n "${GITHUB_ACTIONS:-}" && -n "${value}" ]]; then
    printf '%s\n' "::add-mask::${value}"
  fi
}

write_lifecycle_vars() {
  local lifecycle="$1"
  umask 077
  {
    echo "control_plane: gha"
    echo "gha_mesh_peer_lifecycle: ${lifecycle}"
    if [[ "${lifecycle}" == "present" ]]; then
      echo "gha_wg_public_key: \"${public_key}\""
    fi
  } >"${vars_file}"
  chmod 600 "${vars_file}"
}

[[ $# -eq 2 ]] || usage
provider="$1"
action="$2"
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${project_dir}"

state_dir="${project_dir}/.state/${provider}/gha-peer"
vars_file="${state_dir}/ansible-vars.yml"
iface="${WIREGUARD_INTERFACE:-scwg0}"

mkdir -p "${state_dir}"
chmod 700 "${state_dir}"

case "${action}" in
  present)
    if [[ ! -f "${state_dir}/private.key" ]]; then
      umask 077
      wg genkey >"${state_dir}/private.key"
      chmod 600 "${state_dir}/private.key"
      wg pubkey <"${state_dir}/private.key" >"${state_dir}/public.key"
      chmod 600 "${state_dir}/public.key"
    fi
    private_key="$(tr -d '\n' <"${state_dir}/private.key")"
    public_key="$(tr -d '\n' <"${state_dir}/public.key")"
    mask_value "${private_key}"
    mask_value "${public_key}"

    write_lifecycle_vars present
    bash scripts/ansible-playbook.sh "${provider}" \
      --extra-vars "@${vars_file}" \
      playbooks/gha-mesh-peer.yml

    PROVIDER="${provider}" \
    STATE_DIR="${state_dir}" \
    PRIVATE_KEY="${private_key}" \
    uv run --locked python - <<'PY'
import os
import re
import subprocess
from pathlib import Path

import yaml

provider = os.environ["PROVIDER"]
root = Path.cwd()
state = Path(os.environ["STATE_DIR"])
private_key = os.environ["PRIVATE_KEY"]

main_text = (root / f"inventories/{provider}/group_vars/all/main.yml").read_text(encoding="utf-8")
ci_match = re.search(r"^wireguard_ci_address:\s*[\"']?([^\"'#\n]+)", main_text, re.M)
if ci_match:
  ci_address = ci_match.group(1).strip()
else:
  cidr_match = re.search(r"^wireguard_network_cidr:\s*([0-9.]+)/\d+", main_text, re.M)
  if not cidr_match:
    raise SystemExit("set wireguard_ci_address in group_vars/all/main.yml")
  ci_address = f"{cidr_match.group(1).rsplit('.', 1)[0]}.254"

cidr = re.search(r"^wireguard_network_cidr:\s*([0-9./]+)", main_text, re.M)
if not cidr:
  raise SystemExit("wireguard_network_cidr missing")
mesh_cidr = cidr.group(1)

port_match = re.search(r"^wireguard_listen_port:\s*(\d+)", main_text, re.M)
port = port_match.group(1) if port_match else "51830"

hosts = yaml.safe_load((root / f"inventories/{provider}/hosts.yml").read_text(encoding="utf-8"))
deployment = hosts["all"]["children"]["deployment"]["hosts"]
hub_name = None
hub_endpoint = None
for name in sorted(deployment):
  values = deployment[name] or {}
  if values.get("wireguard_roaming"):
    continue
  endpoint = values.get("wireguard_endpoint")
  if endpoint:
    hub_name = name
    hub_endpoint = f"{endpoint}:{port}"
    break
if not hub_name or not hub_endpoint:
  raise SystemExit("no public static wireguard_endpoint found for CI peer Endpoint")

project = yaml.safe_load((root / "config.yml").read_text(encoding="utf-8"))["project"]
vault = root / f"inventories/{provider}/group_vars/all/vault.yml"
password = root / f"inventories/{provider}/.vault-pass"
label = f"{project}-{provider}"
content = subprocess.check_output(
  [
    "uv",
    "run",
    "--locked",
    "ansible-vault",
    "view",
    "--vault-id",
    f"{label}@{password}",
    str(vault),
  ],
  text=True,
)
document = yaml.safe_load(content)
hub_pub = document["vault_wireguard_public_keys"][hub_name]

if os.environ.get("GITHUB_ACTIONS"):
  for value in (private_key, hub_pub, hub_endpoint, ci_address):
    print(f"::add-mask::{value}", flush=True)

conf = state / "wg.conf"
conf.write_text(
  "\n".join(
    [
      "[Interface]",
      f"PrivateKey = {private_key}",
      f"Address = {ci_address}/32",
      "SaveConfig = false",
      "",
      "[Peer]",
      f"PublicKey = {hub_pub}",
      f"AllowedIPs = {mesh_cidr}",
      f"Endpoint = {hub_endpoint}",
      "PersistentKeepalive = 25",
      "",
    ]
  ),
  encoding="utf-8",
)
conf.chmod(0o600)
PY

    sudo mkdir -p /etc/wireguard
    sudo cp "${state_dir}/wg.conf" "/etc/wireguard/${iface}.conf"
    sudo chmod 600 "/etc/wireguard/${iface}.conf"
    sudo wg-quick down "${iface}" 2>/dev/null || true
    sudo wg-quick up "${iface}"
    echo "GHA mesh peer is up."
    ;;
  absent)
    sudo wg-quick down "${iface}" 2>/dev/null || true
    sudo rm -f "/etc/wireguard/${iface}.conf"
    umask 077
    printf '%s\n' 'control_plane: gha' 'gha_mesh_peer_lifecycle: absent' >"${vars_file}"
    chmod 600 "${vars_file}"
    bash scripts/ansible-playbook.sh "${provider}" \
      --extra-vars "@${vars_file}" \
      playbooks/gha-mesh-peer.yml || true
    rm -rf "${state_dir}"
    echo "GHA mesh peer removed for PROVIDER=${provider}"
    ;;
  *)
    usage
    ;;
esac
