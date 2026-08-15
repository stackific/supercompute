#!/usr/bin/env bash
set -Eeuo pipefail

controller_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=provider.sh
source "${controller_dir}/scripts/provider.sh"
provider_load "${1:-templ-local}"

if [[ ! -f "${provider_vault_password_file}" ]]; then
  echo "Run task vault-init PROVIDER=${provider_name} first; ${provider_vault_password_file} is missing." >&2
  exit 1
fi

if [[ ! -f "${provider_vault_file}" ]]; then
  echo "Run task vault-init PROVIDER=${provider_name} first; ${provider_vault_file} is missing." >&2
  exit 1
fi

cd "${controller_dir}"
exec uv run --locked ansible-vault edit \
  --vault-id "${provider_vault_id}@${provider_vault_password_file}" \
  "${provider_vault_file}"
