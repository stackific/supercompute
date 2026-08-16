#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=provider.sh
source "${project_dir}/scripts/provider.sh"
provider_load "${1:-templ-prod}"

if [[ "${provider_kind}" != "ssh" || $# -gt 1 ]]; then
  echo "Usage: $0 PRODUCTION_INVENTORY_SLUG" >&2
  exit 2
fi

vault_file="${provider_vault_file}"
vault_password_file="${provider_vault_password_file}"
vault_dir="$(dirname "${vault_file}")"
read -r -a inventory_nodes <<<"$(
  cd "${project_dir}"
  uv run --locked python scripts/inventory-node-names.py "${provider_name}"
)"
hosts=("${inventory_nodes[@]}" macos)

if [[ ! -e "${vault_file}" && ! -e "${vault_password_file}" ]]; then
  "${project_dir}/scripts/vault-init.sh" "${provider_name}"
fi
if [[ ! -f "${vault_file}" || ! -f "${vault_password_file}" ]]; then
  echo "Provider Vault state is incomplete. Keep ${vault_file} and ${vault_password_file} together." >&2
  exit 1
fi

vault_plaintext="$(mktemp "${vault_dir}/.vault-prod-wireguard.XXXXXX")"
cleanup() {
  rm -f -- "${vault_plaintext}"
}
trap cleanup EXIT
chmod 600 "${vault_plaintext}"

cd "${project_dir}"
uv run --locked ansible-vault view \
  --vault-id "${provider_vault_id}@${vault_password_file}" \
  "${vault_file}" >"${vault_plaintext}"

state="$(uv run --locked python "${project_dir}/scripts/prod-wireguard-vault.py" \
  status --vault "${vault_plaintext}" --hosts "${hosts[@]}")"
case "${state}" in
  complete)
    uv run --locked python "${project_dir}/scripts/prod-wireguard-vault.py" \
      verify --vault "${vault_plaintext}" --hosts "${hosts[@]}" >/dev/null
    echo "Verified the Vault-managed ${provider_name} WireGuard mesh identity."
    ;;
  absent)
    printf '\n' >>"${vault_plaintext}"
    uv run --locked python "${project_dir}/scripts/prod-wireguard-vault.py" \
      emit --hosts "${hosts[@]}" >>"${vault_plaintext}"
    uv run --locked ansible-vault encrypt \
      --vault-id "${provider_vault_id}@${vault_password_file}" \
      "${vault_plaintext}"
    chmod 600 "${vault_plaintext}"
    mv "${vault_plaintext}" "${vault_file}"
    echo "Added the Vault-managed ${provider_name} WireGuard mesh identity."
    ;;
  *)
    echo "Refusing to repair a partially populated ${provider_name} WireGuard identity in ${vault_file}." >&2
    echo "Restore both key maps from the secret manager or remove both complete maps before retrying." >&2
    exit 1
    ;;
esac
