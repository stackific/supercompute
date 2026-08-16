#!/usr/bin/env bash

set -Eeuo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=provider.sh
source "${project_dir}/scripts/provider.sh"
provider_load "${1:-templ-local}"

if [[ "${provider_kind}" != "lima" ]]; then
  echo "Garage credentials are only defined for the template-local Vault." >&2
  exit 1
fi

vault_file="${provider_vault_file}"
vault_password_file="${provider_vault_password_file}"
vault_dir="$(dirname "${vault_file}")"

if [[ ! -e "${vault_file}" && ! -e "${vault_password_file}" ]]; then
  exec "${project_dir}/scripts/vault-init.sh" "${provider_name}"
fi

if [[ ! -f "${vault_file}" || ! -f "${vault_password_file}" ]]; then
  echo "Provider Vault state is incomplete. Keep ${vault_file} and ${vault_password_file} together." >&2
  exit 1
fi

vault_plaintext="$(mktemp "${vault_dir}/.vault-garage.XXXXXX")"
cleanup() {
  rm -f -- "${vault_plaintext}"
}
trap cleanup EXIT
chmod 600 "${vault_plaintext}"

cd "${project_dir}"
uv run --locked ansible-vault view \
  --vault-id "${provider_vault_id}@${vault_password_file}" \
  "${vault_file}" >"${vault_plaintext}"

garage_fields=(
  vault_garage_access_key
  vault_garage_secret_key
  vault_garage_rpc_secret
  vault_garage_admin_token
  vault_garage_metrics_token
)
garage_fields_present=0
for field in "${garage_fields[@]}"; do
  if grep -Eq "^${field}:[[:space:]]*[^[:space:]]" "${vault_plaintext}"; then
    garage_fields_present=$((garage_fields_present + 1))
  fi
done

if [[ "${garage_fields_present}" == "${#garage_fields[@]}" ]]; then
  exit 0
fi

if [[ "${garage_fields_present}" != 0 ]]; then
  echo "Refusing to repair a partially populated Garage credential set in ${vault_file}." >&2
  echo "Restore the complete five-field set from the secret manager or remove all five fields before retrying." >&2
  exit 1
fi

{
  printf '\n'
  printf "vault_garage_access_key: 'GK%s'\n" "$(/usr/bin/openssl rand -hex 16)"
  printf "vault_garage_secret_key: '%s'\n" "$(/usr/bin/openssl rand -hex 32)"
  printf "vault_garage_rpc_secret: '%s'\n" "$(/usr/bin/openssl rand -hex 32)"
  printf "vault_garage_admin_token: '%s'\n" "$(/usr/bin/openssl rand -base64 32 | tr -d '\n')"
  printf "vault_garage_metrics_token: '%s'\n" "$(/usr/bin/openssl rand -base64 32 | tr -d '\n')"
} >>"${vault_plaintext}"

uv run --locked ansible-vault encrypt \
  --vault-id "${provider_vault_id}@${vault_password_file}" \
  "${vault_plaintext}"
chmod 600 "${vault_plaintext}"
mv "${vault_plaintext}" "${vault_file}"
trap - EXIT

echo "Added the complete Garage credential set to the existing ${provider_name} Vault."
