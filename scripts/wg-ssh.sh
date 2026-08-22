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
  echo "Run task setup before ssh." >&2
  exit 2
}

provider_platform="$("${python_runtime}" "${project_dir}/scripts/provider_platform.py" --provider "${requested_provider}")"

if [[ "${provider_platform}" == "lima" || "${provider_platform}" == "vps" ]]; then
  echo "provider.platform=${provider_platform} is refused; use provider.platform=public." >&2
  exit 2
fi

if [[ "${provider_platform}" != "public" ]]; then
  echo "Unsupported provider platform for WireGuard SSH: ${provider_platform}." >&2
  exit 2
fi

macos_config="${project_dir}/.state/${requested_provider}/wireguard/scwg0.conf"
known_hosts="${project_dir}/.state/${requested_provider}/known_hosts"
[[ -r "${macos_config}" ]] || {
  echo "Missing ${macos_config}; run task up PROVIDER=${requested_provider} first." >&2
  exit 1
}
[[ -r "${known_hosts}" ]] || {
  echo "Missing ${known_hosts}; record verified host keys and run task up PROVIDER=${requested_provider} first." >&2
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
IFS=$'\t' read -r node_address node_user node_port private_key <<<"${connection_values}"
if [[ -z "${node_address}" || -z "${node_user}" || -z "${node_port}" ]]; then
  echo "Could not resolve the production SSH address, user, and port for ${node}." >&2
  exit 1
fi

ssh_identity_args=()
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
