#!/usr/bin/env bash
set -Eeuo pipefail

requested_env="${1:-}"
expected_confirm="${2:-}"

[[ -n "${requested_env}" && -n "${expected_confirm}" ]] || {
  echo "Usage: $0 ENV CONFIRM" >&2
  exit 2
}

[[ "${expected_confirm}" == "down-${requested_env}" ]] || {
  echo "Refusing down. Re-run with CONFIRM=down-${requested_env}" >&2
  exit 2
}

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_runtime="${project_dir}/.venv/bin/python"

[[ -x "${python_runtime}" ]] || {
  echo "Run task setup before down." >&2
  exit 2
}

command -v wg >/dev/null 2>&1 || {
  echo "Install wireguard-tools (wg) before running down." >&2
  exit 1
}

started_at="$(date +%s)"
platform="$("${python_runtime}" "${project_dir}/scripts/provider_platform.py" --provider "${requested_env}")"
case "${platform}" in
  public)
    CONFIRM="${expected_confirm}" bash "${project_dir}/scripts/ansible-playbook.sh" \
      "${requested_env}" playbooks/cluster-down.yml
    CONFIRM="${expected_confirm}" bash "${project_dir}/scripts/ansible-playbook.sh" \
      "${requested_env}" playbooks/wireguard-down.yml
    bash "${project_dir}/scripts/disconnect-wireguard.sh" "${requested_env}"
    ;;
  lima)
    echo "provider.platform=lima is refused; use provider.platform=public." >&2
    exit 2
    ;;
  vps)
    echo "provider.platform=vps is refused; rename to provider.platform=public." >&2
    exit 2
    ;;
  *)
    echo "ENV=${requested_env} has unsupported provider.platform=${platform}." >&2
    exit 2
    ;;
esac

finished_at="$(date +%s)"
elapsed_seconds=$((finished_at - started_at))
elapsed_minutes=$((elapsed_seconds / 60))
elapsed_remainder_seconds=$((elapsed_seconds % 60))
printf 'task down ENV=%s completed in %dm %02ds\n' \
  "${requested_env}" "${elapsed_minutes}" "${elapsed_remainder_seconds}"
