#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=provider.sh
source "${project_dir}/scripts/provider.sh"
provider_load "${1:-templ-local}"

if [[ $# -gt 1 ]]; then
  echo "Usage: $0 [templ-local|templ-prod]" >&2
  exit 2
fi

vault_file="${provider_vault_file}"
vault_password_file="${provider_vault_password_file}"
vault_dir="$(dirname "${vault_file}")"

if [[ ! -e "${vault_file}" && ! -e "${vault_password_file}" ]]; then
  "${project_dir}/scripts/vault-init.sh" "${provider_name}"
fi
if [[ ! -f "${vault_file}" || ! -f "${vault_password_file}" ]]; then
  echo "Provider Vault state is incomplete. Keep ${vault_file} and ${vault_password_file} together." >&2
  exit 1
fi

vault_plaintext="$(mktemp "${vault_dir}/.vault-swarm-secrets.XXXXXX")"
cleanup() {
  rm -f -- "${vault_plaintext}"
}
trap cleanup EXIT
chmod 600 "${vault_plaintext}"

cd "${project_dir}"
uv run --locked ansible-vault view \
  --vault-id "${provider_vault_id}@${vault_password_file}" \
  "${vault_file}" >"${vault_plaintext}"

result="$(uv run --locked python "${project_dir}/scripts/vault-swarm-secrets.py" \
  --vault "${vault_plaintext}" \
  --inventory "${provider_dir}/hosts.yml")"
if [[ "${result}" == "verified" ]]; then
  echo "Verified the Vault-managed ${provider_name} Swarm backup and encryption-at-rest secrets."
  exit 0
fi
if [[ "${result}" != "changed" ]]; then
  echo "Unexpected Vault secret reconciliation result: ${result}" >&2
  exit 1
fi

uv run --locked ansible-vault encrypt \
  --vault-id "${provider_vault_id}@${vault_password_file}" \
  "${vault_plaintext}"
chmod 600 "${vault_plaintext}"
mv "${vault_plaintext}" "${vault_file}"
echo "Added missing ${provider_name} Swarm backup or encryption-at-rest secrets to the encrypted Vault."
