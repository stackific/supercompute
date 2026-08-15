#!/usr/bin/env bash
set -Eeuo pipefail

repository_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project_dir="${repository_dir}"
runtime_dir=/var/run/wireguard
expected_plist_owner=root:wheel
requested_provider="${1:-templ-prod}"
# shellcheck source=provider.sh
source "${repository_dir}/scripts/provider.sh"
provider_load "${requested_provider}"
[[ "${provider_kind}" == "ssh" ]] || {
  echo "Production WireGuard disconnect requires an SSH inventory." >&2
  exit 2
}
deployment_name="$(cd "${repository_dir}" && uv run --locked python scripts/deployment-name.py)"
launchd_label="com.stackific.${deployment_name}.${provider_name}.wireguard"
launchd_path="/Library/LaunchDaemons/${launchd_label}.plist"

if [[ "${DOCKER_SWARM_PROD_WG_DISCONNECT_TEST_MODE:-0}" == "1" ]]; then
  [[ -n "${DOCKER_SWARM_PROD_WG_DISCONNECT_TEST_PROJECT_DIR:-}" ]] || {
    echo "DOCKER_SWARM_PROD_WG_DISCONNECT_TEST_PROJECT_DIR is required in test mode." >&2
    exit 2
  }
  [[ -n "${DOCKER_SWARM_PROD_WG_DISCONNECT_TEST_RUNTIME_DIR:-}" ]] || {
    echo "DOCKER_SWARM_PROD_WG_DISCONNECT_TEST_RUNTIME_DIR is required in test mode." >&2
    exit 2
  }
  [[ -n "${DOCKER_SWARM_PROD_WG_DISCONNECT_TEST_LAUNCHD_PATH:-}" ]] || {
    echo "DOCKER_SWARM_PROD_WG_DISCONNECT_TEST_LAUNCHD_PATH is required in test mode." >&2
    exit 2
  }
  project_dir="${DOCKER_SWARM_PROD_WG_DISCONNECT_TEST_PROJECT_DIR}"
  runtime_dir="${DOCKER_SWARM_PROD_WG_DISCONNECT_TEST_RUNTIME_DIR}"
  launchd_path="${DOCKER_SWARM_PROD_WG_DISCONNECT_TEST_LAUNCHD_PATH}"
  expected_plist_owner="$(id -un):$(id -gn)"
elif [[ -n "${DOCKER_SWARM_PROD_WG_DISCONNECT_TEST_PROJECT_DIR:-}${DOCKER_SWARM_PROD_WG_DISCONNECT_TEST_RUNTIME_DIR:-}${DOCKER_SWARM_PROD_WG_DISCONNECT_TEST_LAUNCHD_PATH:-}" ]]; then
  echo "Production disconnect test overrides require DOCKER_SWARM_PROD_WG_DISCONNECT_TEST_MODE=1." >&2
  exit 2
fi

readonly controller_address=10.217.79.1
readonly config_path="${project_dir}/.state/${provider_name}/wireguard/scwg0.conf"
readonly known_hosts_path="${project_dir}/.state/${provider_name}/known_hosts"
readonly vault_path="${project_dir}/inventories/${provider_name}/group_vars/all/vault.yml"
readonly vault_password_path="${project_dir}/inventories/${provider_name}/.vault-pass"
readonly runtime_name_path="${runtime_dir}/scwg0.name"

for tool in awk grep ifconfig launchctl plutil shasum stat uname uv wg wg-quick; do
  command -v "${tool}" >/dev/null 2>&1 || {
    echo "Cannot disconnect production WireGuard safely: ${tool} is unavailable." >&2
    exit 1
  }
done
[[ "$(uname -s)" == "Darwin" ]] || {
  echo "Production WireGuard disconnect requires the macOS controller." >&2
  exit 1
}

require_private_file() {
  local path="$1"
  [[ -f "${path}" && ! -L "${path}" ]] || {
    echo "Cannot disconnect production WireGuard safely: missing regular file ${path}." >&2
    exit 1
  }
  [[ "$(stat -f '%Lp' "${path}")" == "600" ]] || {
    echo "Cannot disconnect production WireGuard safely: ${path} must have mode 0600." >&2
    exit 1
  }
}

require_private_file "${config_path}"
require_private_file "${known_hosts_path}"
require_private_file "${vault_path}"
require_private_file "${vault_password_path}"

[[ -f "${launchd_path}" && ! -L "${launchd_path}" ]] || {
  echo "Cannot disconnect production WireGuard safely: missing regular file ${launchd_path}." >&2
  exit 1
}
[[ "$(stat -f '%Su:%Sg' "${launchd_path}")" == "${expected_plist_owner}" ]] || {
  echo "Cannot disconnect production WireGuard safely: ${launchd_path} has the wrong owner." >&2
  exit 1
}
[[ "$(stat -f '%Lp' "${launchd_path}")" == "644" ]] || {
  echo "Cannot disconnect production WireGuard safely: ${launchd_path} must have mode 0644." >&2
  exit 1
}

plist_label="$(plutil -extract Label raw -o - "${launchd_path}")"
plist_program="$(plutil -extract ProgramArguments.0 raw -o - "${launchd_path}")"
plist_action="$(plutil -extract ProgramArguments.1 raw -o - "${launchd_path}")"
plist_config="$(plutil -extract ProgramArguments.2 raw -o - "${launchd_path}")"
[[ "${plist_label}" == "${launchd_label}" ]] || {
  echo "Cannot disconnect production WireGuard safely: the launchd label does not match this project." >&2
  exit 1
}
[[ "$(basename "${plist_program}")" == "wg-quick" && -x "${plist_program}" ]] || {
  echo "Cannot disconnect production WireGuard safely: launchd does not name an executable wg-quick." >&2
  exit 1
}
[[ "${plist_action}" == "up" && "${plist_config}" == "${config_path}" ]] || {
  echo "Cannot disconnect production WireGuard safely: launchd does not own ${config_path}." >&2
  exit 1
}

config_address="$(awk '$1 == "Address" && $2 == "=" { split($3, values, "/"); print values[1]; exit }' "${config_path}")"
[[ "${config_address}" == "${controller_address}" ]] || {
  echo "Cannot disconnect production WireGuard safely: ${config_path} does not declare ${controller_address}." >&2
  exit 1
}
config_private_key="$(awk '$1 == "PrivateKey" && $2 == "=" { print $3; exit }' "${config_path}")"
[[ -n "${config_private_key}" ]] || {
  echo "Cannot disconnect production WireGuard safely: ${config_path} has no private key." >&2
  exit 1
}
config_public_key="$(printf '%s\n' "${config_private_key}" | wg pubkey)"
unset config_private_key

preserved_paths=(
  "${config_path}"
  "${known_hosts_path}"
  "${vault_path}"
  "${vault_password_path}"
  "${launchd_path}"
)
preserved_hashes=()
for path in "${preserved_paths[@]}"; do
  preserved_hashes+=("$(shasum -a 256 "${path}" | awk '{print $1}')")
done

sudo -p 'BECOME password: ' -v

launchd_output="$(mktemp "${TMPDIR:-/tmp}/docker-swarm-launchd.XXXXXX")"
cleanup() {
  rm -f -- "${launchd_output}"
}
trap cleanup EXIT

launchd_loaded=false
if sudo launchctl print "system/${launchd_label}" >"${launchd_output}" 2>/dev/null; then
  launchd_loaded=true
  grep -Fq "${plist_program}" "${launchd_output}" || {
    echo "Cannot disconnect production WireGuard safely: the loaded launchd job uses another program." >&2
    exit 1
  }
  grep -Fq "path = ${launchd_path}" "${launchd_output}" || {
    echo "Cannot disconnect production WireGuard safely: the loaded launchd job is not owned by ${launchd_path}." >&2
    exit 1
  }
fi

observed_interfaces=()
while IFS= read -r interface; do
  [[ "${interface}" =~ ^utun[0-9]+$ ]] || continue
  observed_interfaces+=("${interface}")
done < <(ifconfig -l | tr ' ' '\n')
while IFS= read -r interface; do
  [[ "${interface}" =~ ^utun[0-9]+$ ]] || continue
  if [[ " ${observed_interfaces[*]} " != *" ${interface} "* ]]; then
    observed_interfaces+=("${interface}")
  fi
done < <(sudo wg show interfaces | tr ' ' '\n')

interface_args=()
for interface in "${observed_interfaces[@]}"; do
  public_key="$(sudo wg show "${interface}" public-key 2>/dev/null || true)"
  [[ -n "${public_key}" ]] || public_key=not-a-wireguard-interface
  address="$(ifconfig "${interface}" 2>/dev/null | awk '$1 == "inet" { print $2; exit }' || true)"
  [[ -n "${address}" ]] || address=none
  interface_args+=(--interface "${interface},${address},${public_key}")
done

interface="$(
  cd "${repository_dir}"
  uv run --locked python scripts/select-wireguard-interface.py \
    --expected-address "${controller_address}" \
    --expected-public-key "${config_public_key}" \
    "${interface_args[@]}"
)"

original_interface="${interface}"
if [[ -n "${interface}" ]]; then
  [[ "${launchd_loaded}" == "true" ]] || {
    echo "Cannot disconnect production WireGuard safely: ${interface} is active but the project launchd service is not loaded." >&2
    exit 1
  }
  [[ -f "${runtime_name_path}" ]] || {
    echo "Cannot disconnect production WireGuard safely: ${runtime_name_path} is missing." >&2
    exit 1
  }
  runtime_interface="$(sudo awk 'NR == 1 { print $1; exit }' "${runtime_name_path}")"
  [[ "${runtime_interface}" == "${interface}" ]] || {
    echo "Cannot disconnect production WireGuard safely: ${runtime_name_path} names ${runtime_interface}, not ${interface}." >&2
    exit 1
  }
  sudo test -S "${runtime_dir}/${interface}.sock" || {
    echo "Cannot disconnect production WireGuard safely: the runtime socket for ${interface} is missing." >&2
    exit 1
  }
elif [[ -e "${runtime_name_path}" ]]; then
  echo "Cannot disconnect production WireGuard safely: ${runtime_name_path} exists without the verified project interface." >&2
  exit 1
fi

if [[ "${launchd_loaded}" == "true" ]]; then
  echo "Unloading the verified project launchd service."
  sudo launchctl bootout system "${launchd_path}"
  if sudo launchctl print "system/${launchd_label}" >/dev/null 2>&1; then
    echo "Production WireGuard disconnect failed: the project launchd service remains loaded." >&2
    exit 1
  fi
fi

if [[ -n "${interface}" ]] && {
  ifconfig "${interface}" >/dev/null 2>&1 || sudo wg show "${interface}" >/dev/null 2>&1;
}; then
  echo "Stopping verified project interface ${interface} at ${controller_address}."
  sudo wg-quick down "${config_path}"
fi

if [[ -n "${original_interface}" ]] &&
  ! ifconfig "${original_interface}" >/dev/null 2>&1 &&
  ! sudo wg show "${original_interface}" >/dev/null 2>&1 &&
  ! sudo test -S "${runtime_dir}/${original_interface}.sock"; then
  sudo rm -f -- "${runtime_name_path}"
fi

for _ in {1..10}; do
  if ! ifconfig | awk -v expected="${controller_address}" \
    '$1 == "inet" && $2 == expected { found = 1 } END { exit !found }'; then
    break
  fi
  sleep 1
done

if ifconfig | awk -v expected="${controller_address}" \
  '$1 == "inet" && $2 == expected { found = 1 } END { exit !found }'; then
  echo "Production WireGuard disconnect failed: ${controller_address} remains active." >&2
  exit 1
fi
if [[ -n "${original_interface}" ]] && {
  ifconfig "${original_interface}" >/dev/null 2>&1 || sudo wg show "${original_interface}" >/dev/null 2>&1;
}; then
  echo "Production WireGuard disconnect failed: ${original_interface} remains active." >&2
  exit 1
fi
[[ ! -e "${runtime_name_path}" ]] || {
  echo "Production WireGuard disconnect failed: ${runtime_name_path} remains." >&2
  exit 1
}

for index in "${!preserved_paths[@]}"; do
  path="${preserved_paths[${index}]}"
  hash="$(shasum -a 256 "${path}" | awk '{print $1}')"
  [[ "${hash}" == "${preserved_hashes[${index}]}" ]] || {
    echo "Production WireGuard disconnect changed preserved file ${path}." >&2
    exit 1
  }
done

echo "Production controller disconnected; server WireGuard and all preserved controller state were left untouched."
