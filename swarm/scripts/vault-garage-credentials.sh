#!/usr/bin/env bash

set -Eeuo pipefail

repository_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project_dir="${repository_dir}"
if [[ "${DOCKER_SWARM_GARAGE_CREDENTIALS_TEST_MODE:-0}" == "1" ]]; then
  [[ -n "${DOCKER_SWARM_GARAGE_CREDENTIALS_TEST_PROJECT_DIR:-}" ]] || {
    echo "DOCKER_SWARM_GARAGE_CREDENTIALS_TEST_PROJECT_DIR is required in credentials test mode." >&2
    exit 2
  }
  project_dir="${DOCKER_SWARM_GARAGE_CREDENTIALS_TEST_PROJECT_DIR}"
elif [[ -n "${DOCKER_SWARM_GARAGE_CREDENTIALS_TEST_PROJECT_DIR:-}" ]]; then
  echo "Garage credentials test path overrides require DOCKER_SWARM_GARAGE_CREDENTIALS_TEST_MODE=1." >&2
  exit 2
fi
# shellcheck source=scripts/provider.sh
source "${repository_dir}/scripts/provider.sh"
provider_load "${1:-templ-local}"

if [[ "${DOCKER_SWARM_GARAGE_CREDENTIALS_TEST_MODE:-0}" == "1" ]]; then
  provider_vault_file="${project_dir}/inventories/templ-local/group_vars/all/vault.yml"
  provider_vault_password_file="${project_dir}/inventories/templ-local/.vault-pass"
fi

if [[ "${provider_kind}" != "lima" ]]; then
  echo "Garage credentials are only defined for the template-local Vault." >&2
  exit 1
fi

if [[ ! -f "${provider_vault_file}" || ! -f "${provider_vault_password_file}" ]]; then
  echo "Garage credentials do not exist; run: task garage-up PROVIDER=${provider_name}" >&2
  exit 1
fi

vault_plaintext="$(mktemp "${TMPDIR:-/tmp}/docker-swarm-vault-garage.XXXXXX")"
cleanup() {
  rm -f -- "${vault_plaintext}"
}
trap cleanup EXIT
chmod 600 "${vault_plaintext}"

cd "${project_dir}"
uv run --locked ansible-vault view \
  --vault-id "${provider_vault_id}@${provider_vault_password_file}" \
  "${provider_vault_file}" >"${vault_plaintext}"

vault_value() {
  local field="$1"
  local value
  value="$(sed -nE "s/^${field}:[[:space:]]*['\"]?([^'\"]*)['\"]?[[:space:]]*$/\\1/p" "${vault_plaintext}" | head -n 1)"
  [[ -n "${value}" ]] || {
    echo "${field} is missing from the template-local Vault; run: task garage-up" >&2
    exit 1
  }
  printf '%s' "${value}"
}

access_key="$(vault_value vault_garage_access_key)"
secret_key="$(vault_value vault_garage_secret_key)"
deployment_name="$(sed -nE "s/^deployment_name:[[:space:]]*['\"]?([a-z0-9-]+)['\"]?[[:space:]]*$/\1/p" "${repository_dir}/deployment.yml")"
[[ -n "${deployment_name}" ]] || {
  echo "Could not read deployment_name from ${repository_dir}/deployment.yml." >&2
  exit 1
}

printf '%s\n' \
  'export AWS_ENDPOINT_URL="http://127.0.0.1:3901"' \
  'export AWS_DEFAULT_REGION="garage"' \
  "export AWS_ACCESS_KEY_ID=\"${access_key}\"" \
  "export AWS_SECRET_ACCESS_KEY=\"${secret_key}\"" \
  "export GARAGE_BUCKET=\"${deployment_name}-backups\""
