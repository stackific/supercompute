#!/usr/bin/env bash
# Ephemeral WireGuard peer for GitHub Actions runners (control_plane=gha).
set -Eeuo pipefail

usage() {
  echo "Usage: $0 PROVIDER present|absent" >&2
  exit 2
}

[[ $# -eq 2 ]] || usage
provider="$1"
action="$2"
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${project_dir}"

state_dir="${project_dir}/.state/${provider}/gha-peer"
iface="${WIREGUARD_INTERFACE:-scwg0}"

ci_address="$(
  PROVIDER="${provider}" uv run --locked python - <<'PY'
import os
import re
from pathlib import Path

provider = os.environ["PROVIDER"]
text = Path(f"inventories/{provider}/group_vars/all/main.yml").read_text(encoding="utf-8")
match = re.search(r"^wireguard_ci_address:\s*[\"']?([^\"'#\n]+)", text, re.M)
if match:
  print(match.group(1).strip())
else:
  cidr = re.search(r"^wireguard_network_cidr:\s*([0-9.]+)/\d+", text, re.M)
  if not cidr:
    raise SystemExit("set wireguard_ci_address in group_vars/all/main.yml")
  base = cidr.group(1).rsplit(".", 1)[0]
  print(f"{base}.254")
PY
)"

hub_endpoint="$(
  PROVIDER="${provider}" uv run --locked python - <<'PY'
import os
import yaml
from pathlib import Path

provider = os.environ["PROVIDER"]
hosts = yaml.safe_load(Path(f"inventories/{provider}/hosts.yml").read_text(encoding="utf-8"))
deployment = hosts["all"]["children"]["deployment"]["hosts"]
main_text = Path(f"inventories/{provider}/group_vars/all/main.yml").read_text(encoding="utf-8")
import re
port_match = re.search(r"^wireguard_listen_port:\s*(\d+)", main_text, re.M)
port = port_match.group(1) if port_match else "51830"
for name in sorted(deployment):
  values = deployment[name] or {}
  if values.get("wireguard_roaming"):
    continue
  endpoint = values.get("wireguard_endpoint")
  if endpoint:
    print(f"{endpoint}:{port}")
    break
else:
  raise SystemExit("no public static wireguard_endpoint found for CI peer Endpoint")
PY
)"

mkdir -p "${state_dir}"
chmod 700 "${state_dir}"

case "${action}" in
  present)
    if [[ ! -f "${state_dir}/private.key" ]]; then
      umask 077
      wg genkey | tee "${state_dir}/private.key" | wg pubkey >"${state_dir}/public.key"
    fi
    private_key="$(tr -d '\n' <"${state_dir}/private.key")"
    public_key="$(tr -d '\n' <"${state_dir}/public.key")"

    bash scripts/ansible-playbook.sh "${provider}" \
      --extra-vars "control_plane=gha" \
      --extra-vars "gha_wg_public_key=${public_key}" \
      --extra-vars "gha_mesh_peer_lifecycle=present" \
      playbooks/gha-mesh-peer.yml

    umask 077
    cat >"${state_dir}/wg.conf" <<EOF
[Interface]
PrivateKey = ${private_key}
Address = ${ci_address}/32
SaveConfig = false

[Peer]
PublicKey = PLACEHOLDER
AllowedIPs = 0.0.0.0/0
Endpoint = ${hub_endpoint}
PersistentKeepalive = 25
EOF
    # Fill hub public key from vault via ansible/vault helper.
    hub_pub="$(
      PROVIDER="${provider}" uv run --locked python - <<'PY'
import os
import subprocess
import tempfile
from pathlib import Path
import yaml

provider = os.environ["PROVIDER"]
root = Path.cwd()
project = yaml.safe_load((root / "config.yml").read_text(encoding="utf-8"))["project"]
vault = root / f"inventories/{provider}/group_vars/all/vault.yml"
password = root / f"inventories/{provider}/.vault-pass"
label = f"{project}-{provider}"
content = subprocess.check_output(
  [
    "uv", "run", "--locked", "ansible-vault", "view",
    "--vault-id", f"{label}@{password}",
    str(vault),
  ],
  text=True,
)
document = yaml.safe_load(content)
hosts = yaml.safe_load((root / f"inventories/{provider}/hosts.yml").read_text())
deployment = hosts["all"]["children"]["deployment"]["hosts"]
for name in sorted(deployment):
  values = deployment[name] or {}
  if values.get("wireguard_roaming"):
    continue
  print(document["vault_wireguard_public_keys"][name])
  break
PY
    )"
    # shellcheck disable=SC2016
    sed -i.bak "s|PublicKey = PLACEHOLDER|PublicKey = ${hub_pub}|" "${state_dir}/wg.conf"
    rm -f "${state_dir}/wg.conf.bak"

    # AllowedIPs: entire mesh CIDR so Ansible can reach every node over WG.
    mesh_cidr="$(
      PROVIDER="${provider}" uv run --locked python - <<'PY'
import os, re
from pathlib import Path
text = Path(f"inventories/{os.environ['PROVIDER']}/group_vars/all/main.yml").read_text()
print(re.search(r"^wireguard_network_cidr:\s*([0-9./]+)", text, re.M).group(1))
PY
    )"
    sed -i.bak "s|AllowedIPs = 0.0.0.0/0|AllowedIPs = ${mesh_cidr}|" "${state_dir}/wg.conf"
    rm -f "${state_dir}/wg.conf.bak"

    sudo mkdir -p /etc/wireguard
    sudo cp "${state_dir}/wg.conf" "/etc/wireguard/${iface}.conf"
    sudo chmod 600 "/etc/wireguard/${iface}.conf"
    sudo wg-quick down "${iface}" 2>/dev/null || true
    sudo wg-quick up "${iface}"
    echo "GHA mesh peer up: ${ci_address} via ${hub_endpoint}"
    ;;
  absent)
    sudo wg-quick down "${iface}" 2>/dev/null || true
    sudo rm -f "/etc/wireguard/${iface}.conf"
    bash scripts/ansible-playbook.sh "${provider}" \
      --extra-vars "control_plane=gha" \
      --extra-vars "gha_mesh_peer_lifecycle=absent" \
      playbooks/gha-mesh-peer.yml || true
    rm -rf "${state_dir}"
    echo "GHA mesh peer removed for PROVIDER=${provider}"
    ;;
  *)
    usage
    ;;
esac
