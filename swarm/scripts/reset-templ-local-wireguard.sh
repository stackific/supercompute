#!/usr/bin/env bash
set -Eeuo pipefail

repository_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project_dir="${repository_dir}"
wireguard_runtime_dir=/var/run/wireguard
ifconfig_command=/sbin/ifconfig
route_command=/sbin/route

if [[ "${DOCKER_SWARM_RESET_TEST_MODE:-0}" == "1" ]]; then
  [[ -n "${DOCKER_SWARM_RESET_TEST_PROJECT_DIR:-}" ]] || {
    echo "DOCKER_SWARM_RESET_TEST_PROJECT_DIR is required in reset test mode." >&2
    exit 2
  }
  [[ -n "${DOCKER_SWARM_RESET_TEST_BIN_DIR:-}" ]] || {
    echo "DOCKER_SWARM_RESET_TEST_BIN_DIR is required in reset test mode." >&2
    exit 2
  }
  [[ -n "${DOCKER_SWARM_RESET_TEST_RUNTIME_DIR:-}" ]] || {
    echo "DOCKER_SWARM_RESET_TEST_RUNTIME_DIR is required in reset test mode." >&2
    exit 2
  }
  project_dir="${DOCKER_SWARM_RESET_TEST_PROJECT_DIR}"
  wireguard_runtime_dir="${DOCKER_SWARM_RESET_TEST_RUNTIME_DIR}"
  ifconfig_command="${DOCKER_SWARM_RESET_TEST_BIN_DIR}/ifconfig"
  route_command="${DOCKER_SWARM_RESET_TEST_BIN_DIR}/route"
  PATH="${DOCKER_SWARM_RESET_TEST_BIN_DIR}:${PATH}"
  export PATH
elif [[ -n "${DOCKER_SWARM_RESET_TEST_PROJECT_DIR:-}${DOCKER_SWARM_RESET_TEST_BIN_DIR:-}${DOCKER_SWARM_RESET_TEST_RUNTIME_DIR:-}" ]]; then
  echo "Reset test path overrides require DOCKER_SWARM_RESET_TEST_MODE=1." >&2
  exit 2
fi

wireguard_state_dir="${project_dir}/.state/templ-local/wireguard"
template_local_wireguard_address=10.79.0.1
wireguard_configs=(
  "${wireguard_state_dir}/wg.conf"
)

command -v wg >/dev/null 2>&1 || {
  echo "wg is required to identify the active template-local WireGuard interface." >&2
  exit 1
}
command -v wg-quick >/dev/null 2>&1 || {
  echo "wg-quick is required to stop the verified template-local WireGuard interface." >&2
  exit 1
}

config_public_key() {
  local config="$1"
  local private_key

  private_key="$({
    /usr/bin/awk '$1 == "PrivateKey" && $2 == "=" { print $3; exit }' "${config}"
  })"
  [[ -n "${private_key}" ]] || {
    echo "Cannot safely reset: ${config} has no WireGuard PrivateKey." >&2
    return 1
  }
  /usr/bin/printf '%s\n' "${private_key}" | wg pubkey
}

config_address() {
  local config="$1"

  /usr/bin/awk '
    $1 == "Address" && $2 == "=" {
      split($3, values, ",")
      split(values[1], address, "/")
      print address[1]
      exit
    }
  ' "${config}"
}

config_routes() {
  local config="$1"

  /usr/bin/awk '
    $1 == "AllowedIPs" && $2 == "=" {
      for (field_index = 3; field_index <= NF; field_index++) {
        count = split($field_index, values, ",")
        for (value_index = 1; value_index <= count; value_index++) {
          value = values[value_index]
          gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
          sub(/\/.*/, "", value)
          if (value != "") {
            print value
          }
        }
      }
    }
  ' "${config}"
}

interface_address() {
  local interface="$1"

  "${ifconfig_command}" "${interface}" 2>/dev/null |
    /usr/bin/awk '$1 == "inet" { print $2; exit }'
}

interface_route() {
  local destination="$1"

  "${route_command}" -n get -inet "${destination}" 2>/dev/null |
    /usr/bin/awk '$1 == "interface:" { print $2; exit }'
}

observed_interfaces=()
while IFS= read -r interface; do
  [[ -n "${interface}" ]] || continue
  [[ "${interface}" =~ ^utun[0-9]+$ ]] || continue
  observed_interfaces+=("${interface}")
done < <("${ifconfig_command}" -l | /usr/bin/tr ' ' '\n')
while IFS= read -r interface; do
  [[ -n "${interface}" ]] || continue
  [[ "${interface}" =~ ^utun[0-9]+$ ]] || continue
  if [[ " ${observed_interfaces[*]} " != *" ${interface} "* ]]; then
    observed_interfaces+=("${interface}")
  fi
done < <(sudo wg show interfaces | /usr/bin/tr ' ' '\n')

expected_public_key_args=()
valid_configs=()
for config in "${wireguard_configs[@]}"; do
  [[ -f "${config}" ]] || continue
  address="$(config_address "${config}")"
  [[ "${address}" == "${template_local_wireguard_address}" ]] || {
    echo "Cannot safely reset: ${config} does not declare Address ${template_local_wireguard_address}." >&2
    exit 1
  }
  routes=()
  while IFS= read -r route_destination; do
    [[ -n "${route_destination}" ]] || continue
    routes+=("${route_destination}")
  done < <(config_routes "${config}")
  (( ${#routes[@]} > 0 )) || {
    echo "Cannot safely reset: ${config} has no AllowedIPs routes." >&2
    exit 1
  }
  public_key="$(config_public_key "${config}")"
  [[ -n "${public_key}" ]] || {
    echo "Cannot safely reset: could not derive the public key from ${config}." >&2
    exit 1
  }
  valid_configs+=("${config}")
  expected_public_key_args+=(--expected-public-key "${public_key}")
done

interface_args=()
for interface in "${observed_interfaces[@]}"; do
  public_key="$(sudo wg show "${interface}" public-key 2>/dev/null || true)"
  [[ -n "${public_key}" ]] || public_key=not-a-wireguard-interface
  address="$(interface_address "${interface}")"
  [[ -n "${address}" ]] || address=none
  interface_args+=(--interface "${interface},${address},${public_key}")
done

interface="$({
  uv run --locked python "${repository_dir}/scripts/select-wireguard-interface.py" \
    --expected-address "${template_local_wireguard_address}" \
    "${expected_public_key_args[@]}" \
    "${interface_args[@]}"
})"

if [[ -z "${interface}" ]]; then
  for config in "${valid_configs[@]}"; do
    logical_name="$(basename "${config}" .conf)"
    name_file="${wireguard_runtime_dir}/${logical_name}.name"
    [[ -e "${name_file}" ]] || continue
    runtime_interface="$(sudo /usr/bin/awk 'NR == 1 { print $1; exit }' "${name_file}")"
    [[ -n "${runtime_interface}" ]] || {
      echo "Cannot safely reset: ${name_file} is empty." >&2
      exit 1
    }
    if sudo wg show "${runtime_interface}" >/dev/null 2>&1 ||
      "${ifconfig_command}" "${runtime_interface}" >/dev/null 2>&1 ||
      sudo test -S "${wireguard_runtime_dir}/${runtime_interface}.sock"; then
      echo "Cannot safely reset: ${name_file} points to active runtime ${runtime_interface}, but its address/key identity did not match the template-local project." >&2
      exit 1
    fi
    sudo rm -f -- "${name_file}"
    echo "WireGuard: removed stale project name file ${logical_name}.name after proving its interface and socket were absent."
  done
  echo "WireGuard: no active project-owned template-local interface found; checked configuration identity, active addresses/public keys, and project runtime name/socket state."
  exit 0
fi

interface_public_key="$(sudo wg show "${interface}" public-key)"
matching_configs=()
for config in "${valid_configs[@]}"; do
  [[ "$(config_public_key "${config}")" == "${interface_public_key}" ]] || continue
  matching_configs+=("${config}")
done
(( ${#matching_configs[@]} == 1 )) || {
  echo "Cannot safely reset: ${interface} does not map to exactly one project configuration." >&2
  exit 1
}
config="${matching_configs[0]}"
logical_name="$(basename "${config}" .conf)"
name_file="${wireguard_runtime_dir}/${logical_name}.name"
socket_file="${wireguard_runtime_dir}/${interface}.sock"

[[ -f "${name_file}" ]] || {
  echo "Cannot safely reset: ${name_file} is missing for active project interface ${interface}." >&2
  exit 1
}
runtime_interface="$(sudo /usr/bin/awk 'NR == 1 { print $1; exit }' "${name_file}")"
[[ "${runtime_interface}" == "${interface}" ]] || {
  echo "Cannot safely reset: ${name_file} names ${runtime_interface}, not verified interface ${interface}." >&2
  exit 1
}
sudo test -S "${socket_file}" || {
  echo "Cannot safely reset: the verified runtime socket ${socket_file} is missing or is not a socket." >&2
  exit 1
}

routes=()
while IFS= read -r route_destination; do
  [[ -n "${route_destination}" ]] || continue
  routes+=("${route_destination}")
done < <(config_routes "${config}")
for destination in "${routes[@]}"; do
  routed_interface="$(interface_route "${destination}")"
  [[ "${routed_interface}" == "${interface}" ]] || {
    echo "Cannot safely reset: ${destination} routes through ${routed_interface:-no interface}, not verified interface ${interface}." >&2
    exit 1
  }
done

echo "WireGuard: stopping ${interface} only after matching ${config}, ${template_local_wireguard_address}, its public key, ${logical_name}.name, its socket, and every AllowedIPs route."
sudo wg-quick down "${config}"

for _ in {1..10}; do
  if ! "${ifconfig_command}" "${interface}" >/dev/null 2>&1 &&
    ! sudo wg show "${interface}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if "${ifconfig_command}" "${interface}" >/dev/null 2>&1 ||
  sudo wg show "${interface}" >/dev/null 2>&1; then
  echo "Unable to stop verified project-local interface ${interface}; generated project files were preserved and reset stopped." >&2
  exit 1
fi
sudo test ! -e "${socket_file}" || {
  echo "Cannot safely reset: ${socket_file} remains after wg-quick down; generated project files were preserved and reset stopped." >&2
  exit 1
}
sudo test ! -e "${name_file}" || {
  echo "Cannot safely reset: ${name_file} remains after wg-quick down; generated project files were preserved and reset stopped." >&2
  exit 1
}
if "${ifconfig_command}" | /usr/bin/awk -v expected="${template_local_wireguard_address}" \
  '$1 == "inet" && $2 == expected { found = 1 } END { exit !found }'; then
  echo "Cannot safely reset: ${template_local_wireguard_address} remains active after ${interface} stopped; generated project files were preserved and reset stopped." >&2
  exit 1
fi
for destination in "${routes[@]}"; do
  routed_interface="$(interface_route "${destination}")"
  [[ "${routed_interface}" != "${interface}" ]] || {
    echo "Cannot safely reset: ${destination} still routes through ${interface}; generated project files were preserved and reset stopped." >&2
    exit 1
  }
done

stale_name_files=()
for candidate_config in "${valid_configs[@]}"; do
  candidate_logical_name="$(basename "${candidate_config}" .conf)"
  candidate_name_file="${wireguard_runtime_dir}/${candidate_logical_name}.name"
  [[ -e "${candidate_name_file}" ]] || continue
  candidate_interface="$(sudo /usr/bin/awk 'NR == 1 { print $1; exit }' "${candidate_name_file}")"
  [[ -n "${candidate_interface}" ]] || {
    echo "Cannot safely reset: ${candidate_name_file} is empty; generated project state was preserved." >&2
    exit 1
  }
  if sudo wg show "${candidate_interface}" >/dev/null 2>&1 ||
    "${ifconfig_command}" "${candidate_interface}" >/dev/null 2>&1 ||
    sudo test -S "${wireguard_runtime_dir}/${candidate_interface}.sock"; then
    echo "Cannot safely reset: ${candidate_name_file} still points to active runtime ${candidate_interface}; generated project state was preserved." >&2
    exit 1
  fi
  stale_name_files+=("${candidate_name_file}")
done
if (( ${#stale_name_files[@]} > 0 )); then
  for candidate_name_file in "${stale_name_files[@]}"; do
    sudo rm -f -- "${candidate_name_file}"
    sudo test ! -e "${candidate_name_file}" || {
      echo "Cannot safely reset: ${candidate_name_file} remains; generated project state was preserved." >&2
      exit 1
    }
  done
fi

echo "WireGuard: verified removal of interface ${interface}, socket ${interface}.sock, name ${logical_name}.name, address ${template_local_wireguard_address}, and its project routes."
