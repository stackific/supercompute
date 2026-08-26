#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 PROVIDER [ensure|existing|path|remove]" >&2
  exit 2
fi

provider_name="$1"
operation="${2:-ensure}"
case "${operation}" in
  ensure|existing|path|remove) ;;
  *)
    echo "Usage: $0 PROVIDER [ensure|existing|path|remove]" >&2
    exit 2
    ;;
esac

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_runtime="${project_dir}/.venv/bin/python"
[[ -x "${python_runtime}" ]] || {
  echo "Run task setup before resolving the Lima runtime home." >&2
  exit 2
}

cloud_name="$("${python_runtime}" "${project_dir}/scripts/config_project.py")"
node_names="$("${python_runtime}" "${project_dir}/scripts/lima_nodes.py" --provider "${provider_name}")"

lima_system_home="${HOME}/.lima"
lima_provider_home="${lima_system_home}/.${cloud_name}-${provider_name}"

validate_private_directory() {
  local path="$1"
  local mode owner

  if [[ -L "${path}" || ( -e "${path}" && ! -d "${path}" ) ]]; then
    echo "Lima home must be a real directory: ${path}" >&2
    return 1
  fi
  if [[ -d "${path}" ]]; then
    owner="$(/usr/bin/stat -f '%u' "${path}")"
    mode="$(/usr/bin/stat -f '%Lp' "${path}")"
    if [[ "${owner}" != "${UID}" || "${mode}" != "700" ]]; then
      echo "Lima home must be owned by uid ${UID} with mode 0700: ${path}" >&2
      return 1
    fi
  fi
}

validate_socket_budget() {
  local node_name socket_path socket_length

  [[ -n "${node_names}" ]] || {
    echo "Validated Lima inventory has no node_lima_guest hosts." >&2
    return 1
  }

  while IFS= read -r node_name; do
    [[ -n "${node_name}" ]] || continue
    socket_path="${lima_provider_home}/${node_name}/ssh.sock.1234567890123456"
    socket_length="$(LC_ALL=C /usr/bin/printf '%s' "${socket_path}" | /usr/bin/wc -c)"
    socket_length="${socket_length//[[:space:]]/}"
    if (( socket_length >= 104 )); then
      echo "Lima provider home is too long for macOS Unix sockets (${socket_length} bytes): ${lima_provider_home}" >&2
      return 1
    fi
  done <<< "${node_names}"
}

validate_private_directory "${lima_system_home}"

if [[ "${operation}" == "path" ]]; then
  if [[ -e "${lima_provider_home}" ]]; then
    validate_private_directory "${lima_provider_home}"
  fi
  validate_socket_budget
  /usr/bin/printf '%s\n' "${lima_provider_home}"
  exit 0
fi

if [[ "${operation}" == "remove" ]]; then
  if [[ -e "${lima_provider_home}" || -L "${lima_provider_home}" ]]; then
    echo "Refusing to remove non-empty Lima state through the home helper: ${lima_provider_home}" >&2
    exit 1
  fi
  exit 0
fi

if [[ "${operation}" == "existing" ]]; then
  if [[ ! -d "${lima_system_home}" || ! -d "${lima_provider_home}" ]]; then
    echo "Existing Lima runtime home is required: ${lima_provider_home}" >&2
    exit 1
  fi
else
  if [[ ! -e "${lima_system_home}" ]]; then
    /bin/mkdir -m 0700 "${lima_system_home}"
  fi
  if [[ ! -e "${lima_provider_home}" ]]; then
    /bin/mkdir -m 0700 "${lima_provider_home}"
  fi
fi

validate_private_directory "${lima_provider_home}"
validate_socket_budget
/usr/bin/printf '%s\n' "${lima_provider_home}"
