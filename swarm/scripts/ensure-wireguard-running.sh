#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=provider.sh
source "${project_dir}/scripts/provider.sh"
provider_load "${1:-templ-local}"

case "${provider_name}" in
  templ-local)
    expected_address="10.79.0.1"
    config_path="${project_dir}/.state/${provider_name}/wireguard/wg.conf"
    if ! ifconfig | grep -Fq "inet ${expected_address} "; then
      echo "Template-local WireGuard is inactive. Run task wg-up PROVIDER=templ-local interactively." >&2
      exit 1
    fi
    ;;
  templ-prod)
    config_path="${project_dir}/.state/${provider_name}/wireguard/scwg0.conf"
    if [[ ! -r "${config_path}" ]]; then
      echo "The private ${provider_name} WireGuard configuration is missing: ${config_path}. Run task wg-up first." >&2
      exit 1
    fi
    expected_address="$(awk '/^Address = / { split($3, address, "/"); print address[1]; exit }' "${config_path}")"
    if [[ -z "${expected_address}" ]]; then
      echo "Could not read the production controller mesh address from ${config_path}." >&2
      exit 1
    fi
    if ! ifconfig | grep -Fq "inet ${expected_address} "; then
      echo "templ-prod WireGuard is inactive. Its managed system LaunchDaemon should restore it at boot; run task wg-up PROVIDER=templ-prod interactively if it remains absent." >&2
      exit 1
    fi
    ;;
  *)
    echo "Unsupported provider for WireGuard readiness: ${provider_name}." >&2
    exit 2
    ;;
esac

if [[ ! -r "${config_path}" ]]; then
  echo "The private ${provider_name} WireGuard configuration is missing: ${config_path}. Run task wg-up first." >&2
  exit 1
fi
