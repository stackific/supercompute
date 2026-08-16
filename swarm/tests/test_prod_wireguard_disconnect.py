from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/disconnect-prod-wireguard.sh"


class ProductionWireGuardDisconnectTest(unittest.TestCase):
  def setUp(self) -> None:
    self.temporary = tempfile.TemporaryDirectory()
    self.addCleanup(self.temporary.cleanup)
    self.root = Path(self.temporary.name)
    self.project = self.root / "project"
    self.bin_dir = self.root / "bin"
    self.runtime = self.root / "runtime"
    self.launchd_path = self.root / "launchd.plist"
    self.interface_state = self.root / "interfaces"
    self.launchd_state = self.root / "launchd.loaded"
    self.operation_log = self.root / "operations.log"
    for directory in (
      self.project / ".state/templ-prod/wireguard",
      self.project / "inventories/templ-prod/group_vars/all",
      self.bin_dir,
      self.runtime,
    ):
      directory.mkdir(parents=True, exist_ok=True)

    self.config = self.project / ".state/templ-prod/wireguard/scwg0.conf"
    self.known_hosts = self.project / ".state/templ-prod/known_hosts"
    self.vault = self.project / "inventories/templ-prod/group_vars/all/vault.yml"
    self.vault_password = self.project / "inventories/templ-prod/.vault-pass"
    self.config.write_text(
      textwrap.dedent(
        """\
        [Interface]
        PrivateKey = project-private
        Address = 10.217.79.1/24

        [Peer]
        PublicKey = node-public
        AllowedIPs = 10.217.79.11/32
        """
      ),
      encoding="utf-8",
    )
    self.known_hosts.write_text("known-hosts\n", encoding="utf-8")
    self.vault.write_text("encrypted-vault\n", encoding="utf-8")
    self.vault_password.write_text("vault-password\n", encoding="utf-8")
    for path in (self.config, self.known_hosts, self.vault, self.vault_password):
      path.chmod(0o600)
    self.launchd_path.write_text("project launchd definition\n", encoding="utf-8")
    self.launchd_path.chmod(0o644)

    self._write_executable(
      "uname",
      """
      #!/usr/bin/env bash
      [[ "${1:-}" == "-s" ]] && printf 'Darwin\n'
      """,
    )
    self._write_executable(
      "sudo",
      """
      #!/usr/bin/env bash
      set -Eeuo pipefail
      if [[ "${1:-}" == "-p" && "${2:-}" == "BECOME password: " && "${3:-}" == "-v" ]]; then
        exit
      fi
      if [[ "${1:-}" == "test" && "${2:-}" == "-S" ]]; then
        [[ -f "${3:-}" ]]
        exit
      fi
      exec "$@"
      """,
    )
    self._write_executable(
      "plutil",
      """
      #!/usr/bin/env bash
      set -Eeuo pipefail
      case "${2:-}" in
        Label) printf '%s\n' 'com.stackific.sc-swarm3.templ-prod.wireguard' ;;
        ProgramArguments.0) printf '%s\n' "${FAKE_WG_QUICK}" ;;
        ProgramArguments.1) printf '%s\n' 'up' ;;
        ProgramArguments.2) printf '%s\n' "${FAKE_CONFIG}" ;;
        *) exit 2 ;;
      esac
      """,
    )
    self._write_executable(
      "launchctl",
      """
      #!/usr/bin/env bash
      set -Eeuo pipefail
      case "${1:-}" in
        print)
          [[ -f "${FAKE_LAUNCHD_STATE}" ]] || exit 113
          printf 'path = %s\nprogram = %s\narguments = { up %s }\n' \
            "${FAKE_LAUNCHD_PATH}" "${FAKE_WG_QUICK}" "${FAKE_LOADED_CONFIG}"
          ;;
        bootout)
          [[ "${2:-}" == "system" && "${3:-}" == "${FAKE_LAUNCHD_PATH}" ]]
          printf 'launchctl bootout\n' >>"${FAKE_OPERATION_LOG}"
          rm -f -- "${FAKE_LAUNCHD_STATE}"
          ;;
        *) exit 2 ;;
      esac
      """,
    )
    self._write_executable(
      "wg",
      """
      #!/usr/bin/env bash
      set -Eeuo pipefail
      if [[ "${1:-}" == "pubkey" ]]; then
        IFS= read -r private_key
        [[ "${private_key}" == "project-private" ]]
        printf 'project-public\n'
        exit
      fi
      [[ "${1:-}" == "show" ]] || exit 2
      if [[ "${2:-}" == "interfaces" ]]; then
        awk -F '|' '{printf "%s%s", separator, $1; separator=" "} END {print ""}' "${FAKE_INTERFACE_STATE}"
        exit
      fi
      public_key="$(awk -F '|' -v expected="${2:-}" '$1 == expected {print $3; exit}' "${FAKE_INTERFACE_STATE}")"
      [[ -n "${public_key}" ]] || exit 1
      if [[ "${3:-}" == "public-key" ]]; then
        printf '%s\n' "${public_key}"
      fi
      """,
    )
    self._write_executable(
      "ifconfig",
      """
      #!/usr/bin/env bash
      set -Eeuo pipefail
      print_interface() {
        local interface="$1"
        local address
        address="$(awk -F '|' -v expected="${interface}" '$1 == expected {print $2; exit}' "${FAKE_INTERFACE_STATE}")"
        [[ -n "${address}" ]] || return 1
        printf '%s: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1420\n' "${interface}"
        printf '\tinet %s --> %s netmask 0xffffff00\n' "${address}" "${address}"
      }
      if [[ "${1:-}" == "-l" ]]; then
        awk -F '|' '{printf "%s%s", separator, $1; separator=" "} END {print ""}' "${FAKE_INTERFACE_STATE}"
      elif [[ $# -gt 0 ]]; then
        print_interface "$1"
      else
        while IFS='|' read -r interface _; do
          [[ -n "${interface}" ]] && print_interface "${interface}"
        done <"${FAKE_INTERFACE_STATE}"
      fi
      """,
    )
    self._write_executable(
      "wg-quick",
      """
      #!/usr/bin/env bash
      set -Eeuo pipefail
      [[ "${1:-}" == "down" && "${2:-}" == "${FAKE_CONFIG}" ]]
      runtime_interface="$(awk 'NR == 1 {print $1; exit}' "${FAKE_RUNTIME_DIR}/scwg0.name")"
      printf 'wg-quick down %s\n' "${runtime_interface}" >>"${FAKE_OPERATION_LOG}"
      awk -F '|' -v expected="${runtime_interface}" '$1 != expected' \
        "${FAKE_INTERFACE_STATE}" >"${FAKE_INTERFACE_STATE}.new"
      mv "${FAKE_INTERFACE_STATE}.new" "${FAKE_INTERFACE_STATE}"
      rm -f -- "${FAKE_RUNTIME_DIR}/scwg0.name" "${FAKE_RUNTIME_DIR}/${runtime_interface}.sock"
      """,
    )
    self._write_executable(
      "uv",
      """
      #!/usr/bin/env bash
      set -Eeuo pipefail
      [[ "${1:-}" == "run" && "${2:-}" == "--locked" && "${3:-}" == "python" ]]
      shift 3
      exec "${FAKE_PYTHON}" "$@"
      """,
    )

    self.environment = os.environ.copy()
    self.environment.update(
      {
        "FAKE_CONFIG": str(self.config),
        "FAKE_INTERFACE_STATE": str(self.interface_state),
        "FAKE_LAUNCHD_PATH": str(self.launchd_path),
        "FAKE_LOADED_CONFIG": str(self.config),
        "FAKE_LAUNCHD_STATE": str(self.launchd_state),
        "FAKE_OPERATION_LOG": str(self.operation_log),
        "FAKE_PYTHON": os.sys.executable,
        "FAKE_RUNTIME_DIR": str(self.runtime),
        "FAKE_WG_QUICK": str(self.bin_dir / "wg-quick"),
        "PATH": f"{self.bin_dir}:{self.environment['PATH']}",
        "DOCKER_SWARM_PROD_WG_DISCONNECT_TEST_LAUNCHD_PATH": str(self.launchd_path),
        "DOCKER_SWARM_PROD_WG_DISCONNECT_TEST_MODE": "1",
        "DOCKER_SWARM_PROD_WG_DISCONNECT_TEST_PROJECT_DIR": str(self.project),
        "DOCKER_SWARM_PROD_WG_DISCONNECT_TEST_RUNTIME_DIR": str(self.runtime),
      }
    )
    self.interface_state.write_text("utun42|10.217.79.1|project-public\n", encoding="utf-8")
    self.launchd_state.touch()
    (self.runtime / "scwg0.name").write_text("utun42\n", encoding="utf-8")
    (self.runtime / "utun42.sock").touch()

  def _write_executable(self, name: str, content: str) -> None:
    path = self.bin_dir / name
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o700)

  def run_disconnect(self) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
      ["bash", str(SCRIPT)],
      cwd=ROOT,
      env=self.environment,
      text=True,
      capture_output=True,
      check=False,
    )

  def preserved_contents(self) -> dict[Path, bytes]:
    return {
      path: path.read_bytes()
      for path in (
        self.config,
        self.known_hosts,
        self.vault,
        self.vault_password,
        self.launchd_path,
      )
    }

  def test_disconnect_unloads_only_controller_service_and_verified_interface(self) -> None:
    preserved = self.preserved_contents()

    result = self.run_disconnect()

    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn("Production controller disconnected", result.stdout)
    self.assertFalse(self.launchd_state.exists())
    self.assertEqual(self.interface_state.read_text(encoding="utf-8"), "")
    self.assertFalse((self.runtime / "scwg0.name").exists())
    self.assertEqual(
      self.operation_log.read_text(encoding="utf-8").splitlines(),
      ["launchctl bootout", "wg-quick down utun42"],
    )
    for path, content in preserved.items():
      self.assertEqual(path.read_bytes(), content)

  def test_disconnect_accepts_stale_loaded_config_argument_for_owned_job(self) -> None:
    self.environment["FAKE_LOADED_CONFIG"] = "/previous-state/wireguard/scwg0.conf"

    result = self.run_disconnect()

    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertFalse(self.launchd_state.exists())
    self.assertEqual(self.interface_state.read_text(encoding="utf-8"), "")

  def test_refuses_active_interface_when_project_launchd_job_is_not_loaded(self) -> None:
    preserved = self.preserved_contents()
    self.launchd_state.unlink()

    result = self.run_disconnect()

    self.assertNotEqual(result.returncode, 0)
    self.assertIn("active but the project launchd service is not loaded", result.stderr)
    self.assertEqual(
      self.interface_state.read_text(encoding="utf-8"),
      "utun42|10.217.79.1|project-public\n",
    )
    self.assertFalse(self.operation_log.exists())
    for path, content in preserved.items():
      self.assertEqual(path.read_bytes(), content)

  def test_already_disconnected_is_a_preserving_no_op(self) -> None:
    preserved = self.preserved_contents()
    self.launchd_state.unlink()
    self.interface_state.write_text("", encoding="utf-8")
    (self.runtime / "scwg0.name").unlink()
    (self.runtime / "utun42.sock").unlink()

    result = self.run_disconnect()

    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertFalse(self.operation_log.exists())
    for path, content in preserved.items():
      self.assertEqual(path.read_bytes(), content)

  def test_task_dispatch_keeps_template_local_teardown_and_uses_controller_script_for_templ_prod(self) -> None:
    taskfile = (ROOT / "taskfiles/wireguard.yml").read_text(encoding="utf-8")
    remove = taskfile[taskfile.index("  remove:"):taskfile.index("  status:")]
    self.assertIn('eq .PROVIDER "templ-prod"', remove)
    self.assertIn("scripts/disconnect-prod-wireguard.sh", remove)
    self.assertIn('eq .PROVIDER "templ-local"', remove)
    self.assertIn("playbooks/wireguard-remove.yml", remove)
    self.assertNotIn("prod-wireguard-remove", remove)
    script = SCRIPT.read_text(encoding="utf-8")
    self.assertNotIn("ssh ", script)
    self.assertNotIn("systemctl", script)
    self.assertNotIn("ansible-playbook", script)
    self.assertIn("sudo -p 'BECOME password: ' -v", script)

  def test_templ_prod_syntax_check_is_internal_only(self) -> None:
    public_taskfile = (ROOT / "Taskfile.yml").read_text(encoding="utf-8")
    internal_taskfile = (ROOT / "taskfiles/wireguard.yml").read_text(encoding="utf-8")
    setup_guide = (ROOT / "docs/setup-templ-prod.md").read_text(encoding="utf-8")

    self.assertNotIn("prod-syntax-check:", public_taskfile)
    self.assertNotIn("task prod-syntax-check", setup_guide)
    self.assertIn("deps: [':bootstrap:sync', ':wireguard:syntax']", internal_taskfile)


if __name__ == "__main__":
  unittest.main()
