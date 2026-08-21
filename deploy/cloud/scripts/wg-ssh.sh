#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
node="${NODE:-}"
requested_provider="${PROVIDER:-}"
python_runtime="${project_dir}/.venv/bin/python"

[[ -n "${requested_provider}" ]] || {
  echo "PROVIDER must be set." >&2
  exit 2
}
[[ -n "${node}" ]] || {
  echo "NODE must be set." >&2
  exit 2
}
[[ -x "${python_runtime}" ]] || {
  echo "Run task setup before wg-ssh." >&2
  exit 2
}

provider_platform="$("${python_runtime}" "${project_dir}/scripts/provider_platform.py" --provider "${requested_provider}")"

if [[ "${provider_platform}" == "lima" ]]; then
  connection_values="$(
    cd "${project_dir}"
    uv run --locked python scripts/wireguard_ssh_target.py \
      --provider "${requested_provider}" \
      --node "${node}"
  )"
  IFS=$'\t' read -r node_address guest_user macos_address _lima_home macos_config known_hosts lima_identity <<<"${connection_values}"

  [[ -r "${macos_config}" ]] || {
    echo "Missing ${macos_config}; run task wg-up PROVIDER=${requested_provider} first." >&2
    exit 1
  }
  [[ -r "${known_hosts}" ]] || {
    echo "Missing ${known_hosts}; run task wg-up PROVIDER=${requested_provider} first." >&2
    exit 1
  }
  [[ -r "${lima_identity}" ]] || {
    echo "Missing Lima SSH identity: ${lima_identity}" >&2
    exit 1
  }

  if ! ifconfig | grep -Fq "inet ${macos_address} "; then
    sudo wg-quick up "${macos_config}"
  fi

  exec ssh \
    -F /dev/null \
    -i "${lima_identity}" \
    -o IdentitiesOnly=yes \
    -o ControlMaster=no \
    -o ControlPath=none \
    -o StrictHostKeyChecking=accept-new \
    -o "UserKnownHostsFile=${known_hosts}" \
    "${guest_user}@${node_address}"
fi

if [[ "${provider_platform}" != "vps" ]]; then
  echo "Unsupported provider platform for WireGuard SSH: ${provider_platform}." >&2
  exit 2
fi

macos_config="${project_dir}/.state/${requested_provider}/wireguard/scwg0.conf"
known_hosts="${project_dir}/.state/${requested_provider}/known_hosts"
[[ -r "${macos_config}" ]] || {
  echo "Missing ${macos_config}; run task wg-up PROVIDER=${requested_provider} first." >&2
  exit 1
}
[[ -r "${known_hosts}" ]] || {
  echo "Missing ${known_hosts}; record verified host keys and run task wg-up PROVIDER=${requested_provider} first." >&2
  exit 1
}

controller_mesh_address="$(awk '/^Address = / { split($3, address, "/"); print address[1]; exit }' "${macos_config}")"
if [[ -z "${controller_mesh_address}" ]]; then
  echo "Could not read the production controller mesh address from ${macos_config}." >&2
  exit 1
fi

if ! ifconfig | grep -Fq "inet ${controller_mesh_address} "; then
  sudo wg-quick up "${macos_config}"
fi

connection_values="$(
  cd "${project_dir}"
  uv run --locked python scripts/prod-wireguard-ssh-config.py "${requested_provider}" "${node}"
)"
IFS=$'\t' read -r node_address node_user node_port <<<"${connection_values}"
if [[ -z "${node_address}" || -z "${node_user}" || -z "${node_port}" ]]; then
  echo "Could not resolve the production SSH address, user, and port for ${node}." >&2
  exit 1
fi

ssh_identity_args=()
private_key="$(
  cd "${project_dir}"
  uv run --locked python - <<PY
from pathlib import Path
import yaml
main = yaml.safe_load(Path("inventories/${requested_provider}/group_vars/all/main.yml").read_text())
value = main.get("prod_ssh_private_key_file")
print(value if isinstance(value, str) else "")
PY
)"
if [[ -n "${private_key}" ]]; then
  [[ -r "${private_key}" ]] || {
    echo "prod_ssh_private_key_file must name a readable private key: ${private_key}" >&2
    exit 1
  }
  ssh_identity_args=(-i "${private_key}" -o IdentitiesOnly=yes)
fi

exec ssh \
  -F /dev/null \
  -p "${node_port}" \
  -o BatchMode=yes \
  -o ControlMaster=no \
  -o ControlPath=none \
  -o "HostKeyAlias=${node}" \
  -o StrictHostKeyChecking=yes \
  -o "UserKnownHostsFile=${known_hosts}" \
  "${ssh_identity_args[@]}" \
  "${node_user}@${node_address}"
