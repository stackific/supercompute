#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 PROVIDER [ensure|remove]" >&2
  exit 2
fi

provider_name="$1"
operation="${2:-ensure}"
if [[ "${provider_name}" != "templ-local" ]]; then
  echo "Unsupported Lima provider: ${provider_name}" >&2
  exit 2
fi
if [[ "${operation}" != "ensure" && "${operation}" != "remove" ]]; then
  echo "Usage: $0 PROVIDER [ensure|remove]" >&2
  exit 2
fi

lima_system_home="${HOME}/.lima"
lima_provider_home="${lima_system_home}/.${provider_name}"

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

validate_private_directory "${lima_system_home}"

if [[ "${operation}" == "remove" ]]; then
  if [[ -e "${lima_provider_home}" || -L "${lima_provider_home}" ]]; then
    echo "Refusing to remove non-empty Lima state through the home helper: ${lima_provider_home}" >&2
    exit 1
  fi
  exit 0
fi

if [[ ! -e "${lima_system_home}" ]]; then
  /bin/mkdir -m 0700 "${lima_system_home}"
fi
if [[ ! -e "${lima_provider_home}" ]]; then
  /bin/mkdir -m 0700 "${lima_provider_home}"
fi
validate_private_directory "${lima_provider_home}"

longest_socket="${lima_provider_home}/${provider_name}-3/ssh.sock.1234567890123456"
socket_length="$(LC_ALL=C /usr/bin/printf '%s' "${longest_socket}" | /usr/bin/wc -c)"
socket_length="${socket_length//[[:space:]]/}"
if (( socket_length >= 104 )); then
  echo "Lima provider home is too long for macOS Unix sockets (${socket_length} bytes): ${lima_provider_home}" >&2
  exit 1
fi

/usr/bin/printf '%s\n' "${lima_provider_home}"
