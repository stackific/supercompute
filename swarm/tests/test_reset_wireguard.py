from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/select-wireguard-interface.py"
SPEC = importlib.util.spec_from_file_location("select_wireguard_interface", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class LocalWireGuardOwnershipTest(unittest.TestCase):
  def test_selects_only_matching_address_and_public_key(self) -> None:
    interfaces = [
      MODULE.Interface("utun9", "10.79.0.1", "project-key"),
      MODULE.Interface("utun100", "10.217.79.1", "templ-prod-key"),
    ]
    self.assertEqual(
      MODULE.select_interface("10.79.0.1", {"project-key"}, interfaces),
      "utun9",
    )

  def test_does_not_special_case_utun100(self) -> None:
    interfaces = [MODULE.Interface("utun100", "10.217.79.1", "templ-prod-key")]
    self.assertIsNone(MODULE.select_interface("10.79.0.1", {"project-key"}, interfaces))

  def test_refuses_unrelated_interface_at_project_address(self) -> None:
    interfaces = [MODULE.Interface("utun8", "10.79.0.1", "other-key")]
    with self.assertRaisesRegex(ValueError, "unrelated WireGuard interface"):
      MODULE.select_interface("10.79.0.1", {"project-key"}, interfaces)

  def test_refuses_project_key_at_wrong_address(self) -> None:
    interfaces = [MODULE.Interface("utun8", "10.80.0.1", "project-key")]
    with self.assertRaisesRegex(ValueError, "wrong address"):
      MODULE.select_interface("10.79.0.1", {"project-key"}, interfaces)

  def test_refuses_address_owner_when_project_config_is_missing(self) -> None:
    interfaces = [MODULE.Interface("utun8", "10.79.0.1", "unknown-key")]
    with self.assertRaisesRegex(ValueError, "no project configuration"):
      MODULE.select_interface("10.79.0.1", set(), interfaces)

  def test_returns_none_when_no_project_interface_is_active(self) -> None:
    interfaces = [MODULE.Interface("utun8", "10.2.0.2", "vpn-key")]
    self.assertIsNone(MODULE.select_interface("10.79.0.1", set(), interfaces))


class LocalWireGuardResetTest(unittest.TestCase):
  def setUp(self) -> None:
    self.temporary_directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.temporary_directory.cleanup)
    self.test_root = Path(self.temporary_directory.name)
    self.project_dir = self.test_root / "project"
    self.bin_dir = self.test_root / "bin"
    self.runtime_dir = self.test_root / "runtime"
    self.fake_home = self.test_root / "home"
    self.interface_state = self.test_root / "interfaces"
    self.route_state = self.test_root / "routes"
    self.wg_quick_log = self.test_root / "wg-quick.log"
    for directory in (
      self.project_dir / ".state/templ-local/wireguard",
      self.bin_dir,
      self.runtime_dir,
      self.fake_home,
    ):
      directory.mkdir(parents=True, exist_ok=True)

    self._write_executable(
      "sudo",
      """
      #!/usr/bin/env bash
      set -Eeuo pipefail
      if [[ "${1:-}" == "-p" ]]; then
        shift 2
      fi
      if [[ "${1:-}" == "-v" ]]; then
        exit 0
      fi
      if [[ "${1:-}" == "test" && "${2:-}" == "-S" ]]; then
        [[ -f "${3:-}" ]]
        exit
      fi
      exec "$@"
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
    self._write_executable(
      "wg",
      """
      #!/usr/bin/env bash
      set -Eeuo pipefail
      if [[ "${1:-}" == "pubkey" ]]; then
        IFS= read -r private_key
        printf '%s-public\n' "${private_key}"
        exit 0
      fi
      [[ "${1:-}" == "show" ]] || exit 2
      if [[ "${2:-}" == "interfaces" ]]; then
        /usr/bin/awk -F '|' '{printf "%s%s", separator, $1; separator=" "} END {print ""}' "${FAKE_INTERFACE_STATE}"
        exit 0
      fi
      interface="${2:-}"
      public_key="$(/usr/bin/awk -F '|' -v expected="${interface}" '$1 == expected {print $3; exit}' "${FAKE_INTERFACE_STATE}")"
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
      if [[ "${1:-}" == "-l" ]]; then
        /usr/bin/awk -F '|' '{printf "%s%s", separator, $1; separator=" "} END {print ""}' "${FAKE_INTERFACE_STATE}"
        exit 0
      fi
      print_interface() {
        local interface="$1"
        local address
        address="$(/usr/bin/awk -F '|' -v expected="${interface}" '$1 == expected {print $2; exit}' "${FAKE_INTERFACE_STATE}")"
        [[ -n "${address}" ]] || return 1
        printf '%s: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1420\n' "${interface}"
        printf '\tinet %s --> %s netmask 0xffffff00\n' "${address}" "${address}"
      }
      if [[ $# -gt 0 ]]; then
        print_interface "$1"
        exit
      fi
      while IFS='|' read -r interface _; do
        [[ -n "${interface}" ]] || continue
        print_interface "${interface}"
      done <"${FAKE_INTERFACE_STATE}"
      """,
    )
    self._write_executable(
      "route",
      """
      #!/usr/bin/env bash
      set -Eeuo pipefail
      destination="${@: -1}"
      interface="$(/usr/bin/awk -F '|' -v expected="${destination}" '$1 == expected {print $2; exit}' "${FAKE_ROUTE_STATE}")"
      [[ -n "${interface}" ]] || interface=en0
      printf '   route to: %s\n' "${destination}"
      printf '  interface: %s\n' "${interface}"
      """,
    )
    self._write_executable(
      "wg-quick",
      """
      #!/usr/bin/env bash
      set -Eeuo pipefail
      [[ "${1:-}" == "down" && -f "${2:-}" ]] || exit 2
      logical_name="$(basename "$2" .conf)"
      name_file="${DOCKER_SWARM_RESET_TEST_RUNTIME_DIR}/${logical_name}.name"
      [[ -f "${name_file}" ]] || exit 3
      interface="$(/usr/bin/awk 'NR == 1 {print $1; exit}' "${name_file}")"
      printf '%s|%s\n' "${interface}" "$2" >>"${FAKE_WG_QUICK_LOG}"
      /usr/bin/awk -F '|' -v expected="${interface}" '$1 != expected' \
        "${FAKE_INTERFACE_STATE}" >"${FAKE_INTERFACE_STATE}.new"
      /bin/mv "${FAKE_INTERFACE_STATE}.new" "${FAKE_INTERFACE_STATE}"
      /usr/bin/awk -F '|' -v expected="${interface}" \
        'BEGIN {OFS="|"} {$2 = ($2 == expected ? "en0" : $2); print}' \
        "${FAKE_ROUTE_STATE}" >"${FAKE_ROUTE_STATE}.new"
      /bin/mv "${FAKE_ROUTE_STATE}.new" "${FAKE_ROUTE_STATE}"
      /bin/rm -f -- "${DOCKER_SWARM_RESET_TEST_RUNTIME_DIR}/${interface}.sock" "${name_file}"
      """,
    )
    self._write_executable(
      "limactl",
      """
      #!/usr/bin/env bash
      set -Eeuo pipefail
      [[ "${1:-}" == "list" && "${2:-}" == "--quiet" ]] || exit 2
      """,
    )

    self.environment = os.environ.copy()
    self.environment.update(
      {
        "FAKE_INTERFACE_STATE": str(self.interface_state),
        "FAKE_PYTHON": sys.executable,
        "FAKE_ROUTE_STATE": str(self.route_state),
        "FAKE_WG_QUICK_LOG": str(self.wg_quick_log),
        "HOME": str(self.fake_home),
        "PATH": f"{self.bin_dir}:{self.environment['PATH']}",
        "DOCKER_SWARM_RESET_TEST_BIN_DIR": str(self.bin_dir),
        "DOCKER_SWARM_RESET_TEST_MODE": "1",
        "DOCKER_SWARM_RESET_TEST_PROJECT_DIR": str(self.project_dir),
        "DOCKER_SWARM_RESET_TEST_RUNTIME_DIR": str(self.runtime_dir),
      }
    )

  def _write_executable(self, name: str, content: str) -> None:
    path = self.bin_dir / name
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o700)

  def _write_project_config(self) -> Path:
    config = self.project_dir / ".state/templ-local/wireguard/wg.conf"
    config.write_text(
      textwrap.dedent(
        """
        [Interface]
        PrivateKey = project-private
        Address = 10.79.0.1/24

        [Peer]
        PublicKey = node-one-public
        AllowedIPs = 10.79.0.11/32

        [Peer]
        PublicKey = node-two-public
        AllowedIPs = 10.79.0.12/32

        [Peer]
        PublicKey = node-three-public
        AllowedIPs = 10.79.0.13/32
        """
      ).lstrip(),
      encoding="utf-8",
    )
    return config

  def _bind_runtime_socket(self, interface: str) -> Path:
    socket_path = self.runtime_dir / f"{interface}.sock"
    socket_path.touch()
    return socket_path

  def _set_active_interfaces(self, *values: tuple[str, str, str]) -> None:
    self.interface_state.write_text(
      "".join(f"{name}|{address}|{public_key}\n" for name, address, public_key in values),
      encoding="utf-8",
    )

  def _set_routes(self, interface: str) -> None:
    self.route_state.write_text(
      "".join(
        f"{destination}|{interface}\n"
        for destination in ("10.79.0.11", "10.79.0.12", "10.79.0.13")
      ),
      encoding="utf-8",
    )

  def _run_reset(self) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
      [
        "task",
        "--taskfile",
        str(ROOT / "Taskfile.yml"),
        "reset",
        "PROVIDER=templ-local",
        "CONFIRM=reset-templ-local",
      ],
      cwd=self.project_dir,
      env=self.environment,
      text=True,
      capture_output=True,
      check=False,
    )

  def test_reset_proves_identity_and_removes_only_exact_project_interface(self) -> None:
    config = self._write_project_config()
    self._set_active_interfaces(
      ("utun9", "10.79.0.1", "project-private-public"),
      ("utun100", "10.217.79.1", "unrelated-public"),
    )
    self._set_routes("utun9")
    socket_path = self._bind_runtime_socket("utun9")
    name_file = self.runtime_dir / "wg.name"
    name_file.write_text("utun9\n", encoding="utf-8")

    result = self._run_reset()

    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn(
      "stopping utun9 only after matching", result.stdout
    )
    self.assertIn("every AllowedIPs route", result.stdout)
    self.assertIn("verified removal of interface utun9", result.stdout)
    self.assertIn("Verified absent: template-local Vault files and generated state", result.stdout)
    self.assertFalse(config.exists())
    self.assertFalse(socket_path.exists())
    self.assertFalse(name_file.exists())
    self.assertEqual(
      self.interface_state.read_text(encoding="utf-8"),
      "utun100|10.217.79.1|unrelated-public\n",
    )
    self.assertEqual(
      self.wg_quick_log.read_text(encoding="utf-8"),
      f"utun9|{config}\n",
    )
    self.assertNotIn("|utun9\n", self.route_state.read_text(encoding="utf-8"))

  def test_reset_refuses_unrelated_interface_at_project_address_before_deletion(self) -> None:
    config = self._write_project_config()
    self._set_active_interfaces(("utun100", "10.79.0.1", "unrelated-public"))
    self._set_routes("utun100")
    socket_path = self._bind_runtime_socket("utun100")
    name_file = self.runtime_dir / "wg.name"
    name_file.write_text("utun100\n", encoding="utf-8")

    result = self._run_reset()

    self.assertNotEqual(result.returncode, 0)
    self.assertIn("belongs to an unrelated WireGuard interface: utun100", result.stderr)
    self.assertTrue(config.exists())
    self.assertTrue(socket_path.exists())
    self.assertTrue(name_file.exists())
    self.assertFalse(self.wg_quick_log.exists())

  def test_reset_refuses_non_wireguard_utun_at_project_address_before_deletion(self) -> None:
    config = self._write_project_config()
    self._set_active_interfaces(("utun100", "10.79.0.1", ""))
    self._set_routes("utun100")

    result = self._run_reset()

    self.assertNotEqual(result.returncode, 0)
    self.assertIn("belongs to an unrelated WireGuard interface: utun100", result.stderr)
    self.assertTrue(config.exists())
    self.assertFalse(self.wg_quick_log.exists())

  def test_reset_refuses_wrong_route_before_deletion(self) -> None:
    config = self._write_project_config()
    self._set_active_interfaces(("utun9", "10.79.0.1", "project-private-public"))
    self._set_routes("utun9")
    self.route_state.write_text(
      self.route_state.read_text(encoding="utf-8").replace(
        "10.79.0.12|utun9", "10.79.0.12|en0"
      ),
      encoding="utf-8",
    )
    socket_path = self._bind_runtime_socket("utun9")
    name_file = self.runtime_dir / "wg.name"
    name_file.write_text("utun9\n", encoding="utf-8")

    result = self._run_reset()

    self.assertNotEqual(result.returncode, 0)
    self.assertIn("10.79.0.12 routes through en0, not verified interface utun9", result.stderr)
    self.assertTrue(config.exists())
    self.assertTrue(socket_path.exists())
    self.assertTrue(name_file.exists())
    self.assertFalse(self.wg_quick_log.exists())


if __name__ == "__main__":
  unittest.main()
