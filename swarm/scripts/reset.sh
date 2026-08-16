#!/usr/bin/env bash
set -Eeuo pipefail

repository_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project_dir="${repository_dir}"
requested_provider="${1:-}"
confirmation="${2:-}"
case "${requested_provider}" in
  templ-local | templ-prod) ;;
  *)
    echo "PROVIDER must be templ-local or templ-prod." >&2
    exit 2
    ;;
esac
expected_confirmation="reset-${requested_provider}"
[[ "${confirmation}" == "${expected_confirmation}" ]] || {
  echo "Refusing reset. Re-run with CONFIRM=${expected_confirmation}." >&2
  exit 1
}

if [[ "${DOCKER_SWARM_RESET_TEST_MODE:-0}" == "1" ]]; then
  [[ -n "${DOCKER_SWARM_RESET_TEST_PROJECT_DIR:-}" ]] || {
    echo "DOCKER_SWARM_RESET_TEST_PROJECT_DIR is required in reset test mode." >&2
    exit 2
  }
  project_dir="${DOCKER_SWARM_RESET_TEST_PROJECT_DIR}"
elif [[ -n "${DOCKER_SWARM_RESET_TEST_PROJECT_DIR:-}" ]]; then
  echo "Reset test path overrides require DOCKER_SWARM_RESET_TEST_MODE=1." >&2
  exit 2
fi
vault_file="${project_dir}/inventories/${requested_provider}/group_vars/all/vault.yml"
vault_password_file="${project_dir}/inventories/${requested_provider}/.vault-pass"

if [[ "${requested_provider}" == "templ-prod" ]]; then
  rm -f -- "${vault_file}" "${vault_password_file}"
  [[ ! -e "${vault_file}" && ! -L "${vault_file}" ]] || {
    echo "Template-production reset could not remove ${vault_file}." >&2
    exit 1
  }
  [[ ! -e "${vault_password_file}" && ! -L "${vault_password_file}" ]] || {
    echo "Template-production reset could not remove ${vault_password_file}." >&2
    exit 1
  }
  echo "Template-production reset complete: only the provider Vault and Vault password were removed."
  exit 0
fi

state_dir="${project_dir}/.state/${requested_provider}"
if [[ "${DOCKER_SWARM_RESET_TEST_MODE:-0}" == "1" ]]; then
  lima_runtime_home="${project_dir}/.l"
else
  lima_runtime_home="$(bash "${repository_dir}/scripts/lima-runtime-home.sh" "${requested_provider}")"
fi
lima_home_dir="${lima_runtime_home}"
read -r node_one_name node_two_name node_three_name < <(
  cd "${repository_dir}"
  uv run --locked python scripts/lima-node-names.py --shell
)
[[ -n "${node_one_name}" && -n "${node_two_name}" && -n "${node_three_name}" ]] || {
  echo "Could not derive the three template-local node names." >&2
  exit 1
}
lima_nodes=("${node_one_name}" "${node_two_name}" "${node_three_name}")

cd "${project_dir}"

echo "Authenticate before reset changes any template-local resources."
sudo -p 'BECOME password: ' -v

delete_remaining_lima_instances() {
  local node
  local instances

  if [[ ! -d "${lima_home_dir}" ]]; then
    return 0
  fi

  if ! command -v limactl >/dev/null 2>&1; then
    for node in "${lima_nodes[@]}"; do
      if [[ -e "${lima_home_dir}/${node}" ]]; then
        echo "limactl is required to delete existing ${node}; install Lima 2.2.0 and retry." >&2
        exit 1
      fi
    done
    return
  fi

  instances="$(LIMA_HOME="${lima_runtime_home}" limactl list --quiet)"
  for node in "${lima_nodes[@]}"; do
    if /usr/bin/printf '%s\n' "${instances}" | /usr/bin/grep -Fxq "${node}"; then
      echo "Deleting remaining Lima instance ${node}."
      LIMA_HOME="${lima_runtime_home}" limactl delete --force --tty=false "${node}"
    fi
  done
}

destroy_standalone_garage() {
  local shared_profiles

  if ! command -v limactl >/dev/null 2>&1; then
    echo "Reset cannot inspect or remove project Garage resources because limactl is unavailable." >&2
    exit 1
  fi

  shared_profiles="$(env -u LIMA_HOME limactl list --quiet)"
  if ! /usr/bin/printf '%s\n' "${shared_profiles}" | /usr/bin/grep -Fxq default; then
    echo "Lima's shared default profile is absent; no standalone Garage resources remain to remove."
    return 0
  fi

  echo "Destroying only the project-namespaced standalone Garage resources."
  env -u LIMA_HOME task --taskfile "${project_dir}/Taskfile.yml" \
    garage-destroy CONFIRM=destroy-garage-data
}

bash "${repository_dir}/scripts/reset-templ-local-wireguard.sh"

if [[ -f "${vault_file}" && -f "${vault_password_file}" ]]; then
  echo "Destroying Lima VMs through task lima-destroy."
  if ! task --taskfile "${project_dir}/Taskfile.yml" lima-destroy PROVIDER=templ-local CONFIRM=destroy-templ-local; then
    echo "task lima-destroy did not complete; checking the three managed instances directly." >&2
  fi
else
  echo "Vault state is absent or incomplete; checking the three managed Lima instances directly."
fi

delete_remaining_lima_instances
destroy_standalone_garage

echo "Deleting generated template-local state."
rm -f -- "${vault_file}" "${vault_password_file}"
generated_paths=(
  "${state_dir}"
  "${lima_home_dir}"
  "${project_dir}/.venv"
  "${project_dir}/.ansible"
  "${project_dir}/.uv-cache"
  "${project_dir}/.tools"
)
rm -rf -- "${generated_paths[@]}"
if [[ "${DOCKER_SWARM_RESET_TEST_MODE:-0}" != "1" ]]; then
  bash "${repository_dir}/scripts/lima-runtime-home.sh" "${requested_provider}" remove
fi

checked_absent_paths=(
  "${vault_file}"
  "${vault_password_file}"
  "${generated_paths[@]}"
)
for path in "${checked_absent_paths[@]}"; do
  if [[ -e "${path}" || -L "${path}" ]]; then
    echo "Reset could not remove generated project path: ${path}." >&2
    exit 1
  fi
done

echo "Reset complete: the WireGuard, named-VM, and Garage cleanup commands above completed without an error."
echo "Verified absent: template-local Vault files and generated state, Lima home, .venv, .ansible, .uv-cache, and .tools."
echo "Other inventory state and Lima's shared default home were not removed or reconfigured."
