#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 PROVIDER [ansible-playbook arguments...]" >&2
  exit 2
fi

requested_provider="$1"
shift

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
deployment_vars="${project_dir}/deployment.yml"
source "${project_dir}/scripts/provider.sh"
provider_load "${requested_provider}"

if [[ "${provider_kind}" == "lima" && "${DOCKER_SWARM_STANDALONE_GARAGE:-0}" != "1" ]]; then
  LIMA_HOME="$(bash "${project_dir}/scripts/lima-runtime-home.sh" "${provider_name}")"
  export LIMA_HOME
fi

if [[ ! -f "${deployment_vars}" ]]; then
  echo "Deployment configuration does not exist: ${deployment_vars}" >&2
  exit 1
fi

if [[ ! -d "${provider_dir}" ]]; then
  echo "Provider inventory does not exist: ${provider_dir}" >&2
  exit 1
fi

# Interactive production runs may use ssh-agent as usual. Supplying a private
# key path remains an explicit controller transport override for manual
# automation; the server-side backup timer never reads a Mac SSH key.
if [[ "${provider_kind}" == "ssh" && -n "${DOCKER_SWARM_PROD_SSH_PRIVATE_KEY_FILE:-}" ]]; then
  if [[ ! -f "${DOCKER_SWARM_PROD_SSH_PRIVATE_KEY_FILE}" || ! -r "${DOCKER_SWARM_PROD_SSH_PRIVATE_KEY_FILE}" ]]; then
    echo "DOCKER_SWARM_PROD_SSH_PRIVATE_KEY_FILE must name a readable private-key file." >&2
    exit 1
  fi
  export ANSIBLE_PRIVATE_KEY_FILE="${DOCKER_SWARM_PROD_SSH_PRIVATE_KEY_FILE}"
fi

vault_args=()
if [[ -e "${provider_vault_file}" || -e "${provider_vault_password_file}" ]]; then
  if [[ ! -f "${provider_vault_file}" || ! -f "${provider_vault_password_file}" ]]; then
    echo "Provider Vault state is incomplete. Keep ${provider_vault_file} and ${provider_vault_password_file} together, or run task vault-init PROVIDER=${provider_name}." >&2
    exit 1
  fi
  vault_args=(--vault-id "${provider_vault_id}@${provider_vault_password_file}")
fi

cd "${project_dir}"
exec uv run --locked ansible-playbook \
  -i "${provider_dir}" \
  --extra-vars "@${deployment_vars}" \
  --extra-vars "inventory_slug=${provider_name}" \
  "${vault_args[@]}" \
  "$@"
