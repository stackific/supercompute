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
python_runtime="${project_dir}/.venv/bin/python"
provider_dir="${project_dir}/inventories/${requested_provider}"

[[ -x "${python_runtime}" ]] || {
  echo "Run task setup before invoking a playbook." >&2
  exit 2
}

if [[ ! -f "${deployment_vars}" ]]; then
  echo "Deployment configuration does not exist: ${deployment_vars}" >&2
  exit 1
fi

if [[ ! -d "${provider_dir}" || ! -f "${provider_dir}/hosts.yml" ]]; then
  echo "Provider inventory does not exist: ${provider_dir}/hosts.yml" >&2
  exit 1
fi

provider_platform="$("${python_runtime}" "${project_dir}/scripts/provider_platform.py" --provider "${requested_provider}")"
lima_home_mode="${LIMA_RUNTIME_HOME_MODE:-ensure}"
lima_guest_names="$("${python_runtime}" "${project_dir}/scripts/lima_nodes.py" --provider "${requested_provider}")"

if [[ -n "${lima_guest_names}" ]]; then
  if [[ -n "${LIMA_HOME:-}" ]]; then
    expected_lima_home="$(bash "${project_dir}/scripts/lima-runtime-home.sh" "${requested_provider}" path)"
    if [[ "${lima_home_mode}" == "ensure" || "${lima_home_mode}" == "existing" ]]; then
      expected_lima_home="$(bash "${project_dir}/scripts/lima-runtime-home.sh" "${requested_provider}" "${lima_home_mode}")"
    fi
    [[ "${LIMA_HOME}" == "${expected_lima_home}" ]] || {
      echo "LIMA_HOME does not match the validated provider runtime home." >&2
      exit 1
    }
  else
    case "${lima_home_mode}" in
      ensure|existing|path)
        LIMA_HOME="$(bash "${project_dir}/scripts/lima-runtime-home.sh" "${requested_provider}" "${lima_home_mode}")"
        ;;
      *)
        echo "LIMA_RUNTIME_HOME_MODE must be ensure, existing, or path." >&2
        exit 2
        ;;
    esac
  fi
  export LIMA_HOME
fi

vault_args=()
provider_vault_file="${provider_dir}/group_vars/all/vault.yml"
provider_vault_password_file="${provider_dir}/.vault-pass"
deployment_name="$("${python_runtime}" "${project_dir}/scripts/deployment_name.py")"
provider_vault_id="${deployment_name}-${requested_provider}"

if [[ -e "${provider_vault_file}" || -e "${provider_vault_password_file}" ]]; then
  if [[ ! -f "${provider_vault_file}" || ! -f "${provider_vault_password_file}" ]]; then
    echo "Provider Vault state is incomplete. Keep ${provider_vault_file} and ${provider_vault_password_file} together, or run task vault-init PROVIDER=${requested_provider}." >&2
    exit 1
  fi
  vault_args=(--vault-id "${provider_vault_id}@${provider_vault_password_file}")
fi

cd "${project_dir}"
exec uv run --locked ansible-playbook \
  -i "${provider_dir}" \
  --extra-vars "@${deployment_vars}" \
  --extra-vars "inventory_slug=${requested_provider}" \
  "${vault_args[@]}" \
  "$@"
