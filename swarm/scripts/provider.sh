#!/usr/bin/env bash

provider_load() {
  local requested_provider="${1:-templ-local}"
  local controller_dir

  controller_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

  case "${requested_provider}" in
    templ-local)
      provider_name="templ-local"
      provider_vault_id="templ_local"
      provider_dir="${controller_dir}/inventories/templ-local"
      provider_kind="lima"
      ;;
    templ-prod)
      provider_name="templ-prod"
      provider_vault_id="templ_prod"
      provider_dir="${controller_dir}/inventories/templ-prod"
      provider_kind="ssh"
      ;;
    *)
      echo "Unknown PROVIDER '${requested_provider}'. Supported values: templ-local, templ-prod." >&2
      return 1
      ;;
  esac

  provider_vault_file="${provider_dir}/group_vars/all/vault.yml"
  provider_vault_password_file="${provider_dir}/.vault-pass"
}
