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
[[ "${provider_platform}" == "lima" ]] || {
  echo "wg-ssh for PROVIDER=${requested_provider} requires a Lima local provider. Production WireGuard is the next slice." >&2
  exit 2
}

connection_values="$(
  cd "${project_dir}"
  uv run --locked python scripts/wireguard_ssh_target.py \
    --provider "${requested_provider}" \
    --node "${node}"
)"
IFS=$'\t' read -r node_address guest_user macos_address lima_home macos_config known_hosts lima_identity <<<"${connection_values}"

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
