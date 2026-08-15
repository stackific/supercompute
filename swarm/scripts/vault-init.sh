#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=provider.sh
source "${project_dir}/scripts/provider.sh"
provider_load "${1:-templ-local}"
vault_file="${provider_vault_file}"
vault_password_file="${provider_vault_password_file}"
vault_dir="$(dirname "${vault_file}")"

command -v uv >/dev/null 2>&1 || {
  echo "uv is required; install it, then run task setup." >&2
  exit 1
}
if [[ -e "${vault_file}" || -e "${vault_password_file}" ]]; then
  echo "Refusing to replace existing ${provider_name} Vault state. Rekey it with ansible-vault or reset the provider deliberately." >&2
  exit 1
fi

if [[ "${provider_kind}" == "lima" ]]; then
  command -v wg >/dev/null 2>&1 || {
    echo "wg is required; install wireguard-tools before initializing the template-local Vault." >&2
    exit 1
  }

fi

mkdir -p "${vault_dir}"
vault_file_tmp="$(mktemp "${vault_dir}/.vault.yml.XXXXXX")"
vault_password_file_tmp="$(mktemp "${vault_dir}/.vault-pass.XXXXXX")"
age_identity_file=""
cleanup() {
  rm -f -- "${vault_file_tmp}" "${vault_password_file_tmp}"
  if [[ -n "${age_identity_file}" ]]; then
    rm -f -- "${age_identity_file}"
  fi
}
trap cleanup EXIT

umask 077
/usr/bin/openssl rand -base64 48 >"${vault_password_file_tmp}"
chmod 600 "${vault_password_file_tmp}"

if [[ "${provider_kind}" == "lima" ]]; then
  read -r node_one_name node_two_name node_three_name < <(
    cd "${project_dir}"
    uv run --locked python scripts/lima-node-names.py --shell
  )
  [[ -n "${node_one_name}" && -n "${node_two_name}" && -n "${node_three_name}" ]] || {
    echo "Could not derive the three template-local node names." >&2
    exit 1
  }

  macos_private="$(wg genkey)"
  node_one_private="$(wg genkey)"
  node_two_private="$(wg genkey)"
  node_three_private="$(wg genkey)"
  macos_public="$(printf '%s' "${macos_private}" | wg pubkey)"
  node_one_public="$(printf '%s' "${node_one_private}" | wg pubkey)"
  node_two_public="$(printf '%s' "${node_two_private}" | wg pubkey)"
  node_three_public="$(printf '%s' "${node_three_private}" | wg pubkey)"

  {
    printf '%s\n' 'vault_wireguard_private_keys:'
    printf "  macos: '%s'\n" "${macos_private}"
    printf "  %s: '%s'\n" "${node_one_name}" "${node_one_private}"
    printf "  %s: '%s'\n" "${node_two_name}" "${node_two_private}"
    printf "  %s: '%s'\n" "${node_three_name}" "${node_three_private}"
    printf '%s\n' 'vault_wireguard_public_keys:'
    printf "  macos: '%s'\n" "${macos_public}"
    printf "  %s: '%s'\n" "${node_one_name}" "${node_one_public}"
    printf "  %s: '%s'\n" "${node_two_name}" "${node_two_public}"
    printf "  %s: '%s'\n" "${node_three_name}" "${node_three_public}"
    printf "vault_garage_access_key: 'GK%s'\n" "$(/usr/bin/openssl rand -hex 16)"
    printf "vault_garage_secret_key: '%s'\n" "$(/usr/bin/openssl rand -hex 32)"
    printf "vault_garage_rpc_secret: '%s'\n" "$(/usr/bin/openssl rand -hex 32)"
    printf "vault_garage_admin_token: '%s'\n" "$(/usr/bin/openssl rand -base64 32 | tr -d '\n')"
    printf "vault_garage_metrics_token: '%s'\n" "$(/usr/bin/openssl rand -base64 32 | tr -d '\n')"
    printf "vault_swarm_backup_restic_password: '%s'\n" "$(/usr/bin/openssl rand -base64 48 | tr -d '\n')"
    printf '%s\n' 'vault_encryption_at_rest_passphrases:'
    printf "  %s: '%s'\n" "${node_one_name}" "$(/usr/bin/openssl rand -base64 48 | tr -d '\n')"
    printf "  %s: '%s'\n" "${node_two_name}" "$(/usr/bin/openssl rand -base64 48 | tr -d '\n')"
    printf "  %s: '%s'\n" "${node_three_name}" "$(/usr/bin/openssl rand -base64 48 | tr -d '\n')"
  } >"${vault_file_tmp}"
else
  read -r -a production_nodes <<<"$(
    cd "${project_dir}"
    uv run --locked python scripts/inventory-node-names.py "${provider_name}"
  )"
  {
    printf "vault_provider_name: '%s'\n" "${provider_name}"
    (
      cd "${project_dir}"
      uv run --locked python "${project_dir}/scripts/prod-wireguard-vault.py" \
        emit --hosts "${production_nodes[@]}" macos
    )
    printf "vault_swarm_backup_restic_password: '%s'\n" "$(/usr/bin/openssl rand -base64 48 | tr -d '\n')"
    printf '%s\n' 'vault_encryption_at_rest_passphrases:'
    for node in "${production_nodes[@]}"; do
      printf "  %s: '%s'\n" "${node}" "$(/usr/bin/openssl rand -base64 48 | tr -d '\n')"
    done
  } >"${vault_file_tmp}"
fi

cd "${project_dir}"
uv run --locked ansible-vault encrypt --vault-id "${provider_vault_id}@${vault_password_file_tmp}" "${vault_file_tmp}"
chmod 600 "${vault_file_tmp}"
mv "${vault_file_tmp}" "${vault_file}"
mv "${vault_password_file_tmp}" "${vault_password_file}"

echo "Created encrypted ${provider_name} WireGuard, backup, and storage material in ${vault_file}."
echo "Keep ${vault_password_file} and the encrypted Vault file together and private."
