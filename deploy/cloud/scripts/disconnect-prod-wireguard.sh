#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir=/var/run/wireguard
expected_plist_owner=root:wheel
requested_provider="${1:-}"
python_runtime="${project_dir}/.venv/bin/python"

[[ -n "${requested_provider}" ]] || {
  echo "Usage: $0 PROVIDER" >&2
  exit 2
}
[[ -x "${python_runtime}" ]] || {
  echo "Run task setup before disconnecting production WireGuard." >&2
  exit 2
}

provider_platform="$("${python_runtime}" "${project_dir}/scripts/provider_platform.py" --provider "${requested_provider}")"
[[ "${provider_platform}" == "vps" ]] || {
  echo "Production WireGuard disconnect requires a VPS inventory (provider.platform=vps)." >&2
  exit 2
}

deployment_name="$("${python_runtime}" "${project_dir}/scripts/deployment_name.py")"
launchd_label="com.stackific.${deployment_name}.${requested_provider}.wireguard"
launchd_path="/Library/LaunchDaemons/${launchd_label}.plist"

if [[ "${DEPLOY_CLOUD_PROD_WG_DISCONNECT_TEST_MODE:-0}" == "1" ]]; then
  [[ -n "${DEPLOY_CLOUD_PROD_WG_DISCONNECT_TEST_PROJECT_DIR:-}" ]] || {
    echo "DEPLOY_CLOUD_PROD_WG_DISCONNECT_TEST_PROJECT_DIR is required in test mode." >&2
    exit 2
  }
  [[ -n "${DEPLOY_CLOUD_PROD_WG_DISCONNECT_TEST_RUNTIME_DIR:-}" ]] || {
    echo "DEPLOY_CLOUD_PROD_WG_DISCONNECT_TEST_RUNTIME_DIR is required in test mode." >&2
    exit 2
  }
  [[ -n "${DEPLOY_CLOUD_PROD_WG_DISCONNECT_TEST_LAUNCHD_PATH:-}" ]] || {
    echo "DEPLOY_CLOUD_PROD_WG_DISCONNECT_TEST_LAUNCHD_PATH is required in test mode." >&2
    exit 2
  }
  project_dir="${DEPLOY_CLOUD_PROD_WG_DISCONNECT_TEST_PROJECT_DIR}"
  runtime_dir="${DEPLOY_CLOUD_PROD_WG_DISCONNECT_TEST_RUNTIME_DIR}"
  launchd_path="${DEPLOY_CLOUD_PROD_WG_DISCONNECT_TEST_LAUNCHD_PATH}"
  expected_plist_owner="$(id -un):$(id -gn)"
elif [[ -n "${DEPLOY_CLOUD_PROD_WG_DISCONNECT_TEST_PROJECT_DIR:-}${DEPLOY_CLOUD_PROD_WG_DISCONNECT_TEST_RUNTIME_DIR:-}${DEPLOY_CLOUD_PROD_WG_DISCONNECT_TEST_LAUNCHD_PATH:-}" ]]; then
  echo "Production disconnect test overrides require DEPLOY_CLOUD_PROD_WG_DISCONNECT_TEST_MODE=1." >&2
  exit 2
fi

read -r controller_address interface_name config_path known_hosts_path < <(
  cd "${project_dir}"
  uv run --locked python - <<PY
from pathlib import Path
import yaml
root = Path("${project_dir}")
provider = "${requested_provider}"
main = yaml.safe_load((root / "inventories" / provider / "group_vars/all/main.yml").read_text())
address = main["prod_wireguard_controller_address"]
iface = main["prod_wireguard_interface"]
state = root / ".state" / provider
print(address, iface, state / "wireguard" / f"{iface}.conf", state / "known_hosts")
PY
)

vault_path="${project_dir}/inventories/${requested_provider}/group_vars/all/vault.yml"
vault_password_path="${project_dir}/inventories/${requested_provider}/.vault-pass"
runtime_name_path="${runtime_dir}/${interface_name}.name"

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

launchd_present=false
if [[ -f "${launchd_path}" && ! -L "${launchd_path}" ]]; then
  launchd_present=true
elif ifconfig | awk -v expected="${controller_address}" \
  '$1 == "inet" && $2 == expected { found = 1 } END { exit !found }'; then
  echo "LaunchDaemon ${launchd_path} is missing but ${controller_address} is active."
  echo "Disconnecting via ${config_path} only (common after renaming deployment_name)."
  echo "Remove any orphaned /Library/LaunchDaemons/com.stackific.*.prod.wireguard.plist manually if present."
else
  echo "Production controller already disconnected for label ${launchd_label} (no ${launchd_path}; ${controller_address} is inactive)."
  exit 0
fi

if [[ "${launchd_present}" == "true" ]]; then
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
else
  plist_program="$(command -v wg-quick)"
fi

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
)
if [[ "${launchd_present}" == "true" ]]; then
  preserved_paths+=("${launchd_path}")
fi
preserved_hashes=()
for path in "${preserved_paths[@]}"; do
  preserved_hashes+=("$(shasum -a 256 "${path}" | awk '{print $1}')")
done

sudo -p 'BECOME password: ' -v

launchd_output="$(mktemp "${TMPDIR:-/tmp}/deploy-cloud-launchd.XXXXXX")"
cleanup() {
  rm -f -- "${launchd_output}"
}
trap cleanup EXIT

launchd_loaded=false
if [[ "${launchd_present}" == "true" ]] &&
  sudo launchctl print "system/${launchd_label}" >"${launchd_output}" 2>/dev/null; then
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
  cd "${project_dir}"
  uv run --locked python scripts/select-wireguard-interface.py \
    --expected-address "${controller_address}" \
    --expected-public-key "${config_public_key}" \
    "${interface_args[@]}"
)"

original_interface="${interface}"
if [[ -n "${interface}" ]]; then
  if [[ "${launchd_present}" == "true" ]]; then
    [[ "${launchd_loaded}" == "true" ]] || {
      echo "Cannot disconnect production WireGuard safely: ${interface} is active but the project launchd service is not loaded." >&2
      exit 1
    }
  fi
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
