#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
node="${NODE:-}"
requested_provider="${PROVIDER:-templ-local}"
# shellcheck source=provider.sh
source "${project_dir}/scripts/provider.sh"
provider_load "${requested_provider}"

if [[ "${provider_kind}" == "lima" ]]; then
  read -r node_one_name node_two_name node_three_name < <(
    cd "${project_dir}"
    uv run --locked python scripts/lima-node-names.py --shell
  )
  [[ -n "${node_one_name}" && -n "${node_two_name}" && -n "${node_three_name}" ]] || {
    echo "Could not derive the three template-local node names." >&2
    exit 1
  }

  guest_user="${USER:?USER must be set}"
  macos_config="${project_dir}/.state/${provider_name}/wireguard/wg.conf"
  known_hosts="${project_dir}/.state/${provider_name}/wireguard/known_hosts"
  lima_home="$(bash "${project_dir}/scripts/lima-runtime-home.sh" "${provider_name}")"
  lima_identity="${lima_home}/_config/user"

  case "${node}" in
    "${node_one_name}") node_address=10.79.0.11 ;;
    "${node_two_name}") node_address=10.79.0.12 ;;
    "${node_three_name}") node_address=10.79.0.13 ;;
    *)
      echo "NODE must be ${node_one_name}, ${node_two_name}, or ${node_three_name}." >&2
      exit 2
      ;;
  esac

  [[ -r "${macos_config}" ]] || {
    echo "Missing ${macos_config}; run task wg-up PROVIDER=templ-local first." >&2
    exit 1
  }
  [[ -r "${known_hosts}" ]] || {
    echo "Missing ${known_hosts}; run task wg-up PROVIDER=templ-local first." >&2
    exit 1
  }
  [[ -r "${lima_identity}" ]] || {
    echo "Missing Lima SSH identity: ${lima_identity}" >&2
    exit 1
  }

  if ! ifconfig | grep -Fq 'inet 10.79.0.1 '; then
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

if [[ "${provider_kind}" != "ssh" ]]; then
  echo "Unsupported provider for WireGuard SSH: ${provider_name}." >&2
  exit 2
fi

macos_config="${project_dir}/.state/${provider_name}/wireguard/scwg0.conf"
known_hosts="${project_dir}/.state/${provider_name}/known_hosts"
[[ -r "${macos_config}" ]] || {
  echo "Missing ${macos_config}; run task wg-up PROVIDER=templ-prod first." >&2
  exit 1
}
[[ -r "${known_hosts}" ]] || {
  echo "Missing ${known_hosts}; record verified host keys and run task wg-up PROVIDER=templ-prod first." >&2
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
  uv run --locked python scripts/prod-wireguard-ssh-config.py "${provider_name}" "${node}"
)"
IFS=$'\t' read -r node_address node_user node_port <<<"${connection_values}"
if [[ -z "${node_address}" || -z "${node_user}" || -z "${node_port}" ]]; then
  echo "Could not resolve the templ-prod SSH address, user, and port for ${node}." >&2
  exit 1
fi

ssh_identity_args=()
if [[ -n "${DOCKER_SWARM_PROD_SSH_PRIVATE_KEY_FILE:-}" ]]; then
  if [[ ! -r "${DOCKER_SWARM_PROD_SSH_PRIVATE_KEY_FILE}" ]]; then
    echo "DOCKER_SWARM_PROD_SSH_PRIVATE_KEY_FILE must name a readable private key." >&2
    exit 1
  fi
  ssh_identity_args=(-i "${DOCKER_SWARM_PROD_SSH_PRIVATE_KEY_FILE}" -o IdentitiesOnly=yes)
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
