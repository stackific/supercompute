from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/prod-known-hosts.py"
NODES = ("templ-prod-1", "templ-prod-2", "templ-prod-3")
ENDPOINTS = ("203.0.113.11", "203.0.113.12", "203.0.113.13")


def key(index: int) -> str:
  return base64.b64encode(f"test-ed25519-key-{index}".encode()).decode()


def fingerprint(encoded_key: str) -> str:
  digest = hashlib.sha256(base64.b64decode(encoded_key)).digest()
  return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


class ProductionKnownHostsTest(unittest.TestCase):
  def setUp(self) -> None:
    self.temporary = tempfile.TemporaryDirectory()
    self.root = Path(self.temporary.name)
    self.inventory = self.root / "hosts.yml"
    self.known_hosts = self.root / "state" / "known_hosts"
    self.bin_dir = self.root / "bin"
    self.bin_dir.mkdir(mode=0o700)
    scanner = self.bin_dir / "ssh-keyscan"
    scanner.write_text(
      textwrap.dedent(
        """\
        #!/usr/bin/env python3
        import json
        import os
        import sys

        endpoint = sys.argv[-1]
        response = json.loads(os.environ["FAKE_SSH_KEYSCAN"])[endpoint]
        if response.get("stdout"):
          print(response["stdout"])
        raise SystemExit(response.get("rc", 0))
        """
      ),
      encoding="utf-8",
    )
    scanner.chmod(0o700)
    self.keys = tuple(key(index) for index in range(1, 4))
    self.write_inventory()

  def tearDown(self) -> None:
    self.temporary.cleanup()

  def write_inventory(
    self,
    *,
    endpoints: tuple[str, str, str] = ENDPOINTS,
    fingerprints: tuple[str, str, str] | None = None,
  ) -> None:
    if fingerprints is None:
      fingerprints = tuple(fingerprint(item) for item in self.keys)
    hosts = {
      node: {
        "prod_wireguard_endpoint": endpoint,
        "prod_ssh_host_ed25519_sha256": expected,
      }
      for node, endpoint, expected in zip(NODES, endpoints, fingerprints, strict=True)
    }
    inventory = {
      "all": {
        "children": {
          "wireguard_nodes": {"hosts": hosts},
        },
      },
    }
    self.inventory.write_text(yaml.safe_dump(inventory, sort_keys=False), encoding="utf-8")

  def responses(self) -> dict[str, dict[str, object]]:
    return {
      endpoint: {"stdout": f"{endpoint} ssh-ed25519 {encoded_key}", "rc": 0}
      for endpoint, encoded_key in zip(ENDPOINTS, self.keys, strict=True)
    }

  def run_script(
    self,
    responses: dict[str, dict[str, object]] | None = None,
    *,
    reuse_existing: bool = False,
  ) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PATH"] = f"{self.bin_dir}{os.pathsep}{environment['PATH']}"
    environment["FAKE_SSH_KEYSCAN"] = json.dumps(responses or self.responses())
    command = [
        sys.executable,
        str(SCRIPT),
        "--inventory",
        str(self.inventory),
        "--known-hosts",
        str(self.known_hosts),
      ]
    if reuse_existing:
      command.append("--reuse-existing")
    return subprocess.run(
      command,
      capture_output=True,
      check=False,
      env=environment,
      text=True,
    )

  def seed_known_hosts(self) -> bytes:
    previous = b"previous-valid-known-hosts\n"
    self.known_hosts.parent.mkdir(mode=0o700)
    self.known_hosts.write_bytes(previous)
    self.known_hosts.chmod(0o600)
    return previous

  def assert_previous_preserved(self, previous: bytes) -> None:
    self.assertEqual(self.known_hosts.read_bytes(), previous)
    self.assertEqual(stat.S_IMODE(self.known_hosts.stat().st_mode), 0o600)

  def test_success_installs_stable_aliases_with_private_modes_and_full_report(self) -> None:
    result = self.run_script()

    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn("CHANGED=1", result.stdout)
    self.assertEqual(stat.S_IMODE(self.known_hosts.parent.stat().st_mode), 0o700)
    self.assertEqual(stat.S_IMODE(self.known_hosts.stat().st_mode), 0o600)
    lines = self.known_hosts.read_text(encoding="utf-8").splitlines()
    self.assertEqual(
      lines,
      [f"{node} ssh-ed25519 {encoded_key}" for node, encoded_key in zip(NODES, self.keys, strict=True)],
    )
    for node, endpoint, encoded_key in zip(NODES, ENDPOINTS, self.keys, strict=True):
      expected = fingerprint(encoded_key)
      self.assertIn(
        f"node={node} endpoint={endpoint} expected={expected} observed={expected} result=match",
        result.stdout,
      )
    self.assertEqual(list(self.known_hosts.parent.glob(".known_hosts.*")), [])

  def test_idempotent_success_does_not_replace_the_file(self) -> None:
    first = self.run_script()
    self.assertEqual(first.returncode, 0, first.stderr)
    first_inode = self.known_hosts.stat().st_ino

    second = self.run_script()

    self.assertEqual(second.returncode, 0, second.stderr)
    self.assertIn("CHANGED=0", second.stdout)
    self.assertEqual(self.known_hosts.stat().st_ino, first_inode)

  def test_reuses_verified_alias_file_without_public_scan(self) -> None:
    first = self.run_script()
    self.assertEqual(first.returncode, 0, first.stderr)
    unreachable = {endpoint: {"rc": 1} for endpoint in ENDPOINTS}

    second = self.run_script(unreachable, reuse_existing=True)

    self.assertEqual(second.returncode, 0, second.stderr)
    self.assertIn("result=reused", second.stdout)
    self.assertIn("CHANGED=0 reused verified", second.stdout)

  def test_reuse_rejects_alias_file_that_no_longer_matches_inventory(self) -> None:
    first = self.run_script()
    self.assertEqual(first.returncode, 0, first.stderr)
    content = self.known_hosts.read_text(encoding="utf-8")
    self.known_hosts.write_text(content.replace(self.keys[0], key(99)), encoding="utf-8")

    result = self.run_script(reuse_existing=True)

    self.assertNotEqual(result.returncode, 0)
    self.assertIn("existing known_hosts fingerprint mismatch", result.stderr)

  def test_mismatch_reports_observed_fingerprint_and_preserves_prior_file(self) -> None:
    previous = self.seed_known_hosts()
    fingerprints = list(tuple(fingerprint(item) for item in self.keys))
    fingerprints[1] = fingerprint(key(99))
    self.write_inventory(fingerprints=tuple(fingerprints))

    result = self.run_script()

    self.assertNotEqual(result.returncode, 0)
    self.assertIn("templ-prod-2: ED25519 host-key fingerprint mismatch", result.stderr)
    self.assertIn(f"observed={fingerprint(self.keys[1])} result=REJECTED", result.stdout)
    self.assert_previous_preserved(previous)

  def test_partial_unreachable_scan_checks_every_node_and_preserves_prior_file(self) -> None:
    previous = self.seed_known_hosts()
    responses = self.responses()
    responses[ENDPOINTS[1]] = {"rc": 1}

    result = self.run_script(responses)

    self.assertNotEqual(result.returncode, 0)
    self.assertIn("templ-prod-2: endpoint returned no ED25519 host key", result.stderr)
    for node in NODES:
      self.assertIn(f"node={node}", result.stdout)
    self.assert_previous_preserved(previous)

  def test_wrong_key_type_is_rejected_and_prior_file_is_preserved(self) -> None:
    previous = self.seed_known_hosts()
    responses = self.responses()
    responses[ENDPOINTS[0]] = {"stdout": f"{ENDPOINTS[0]} ssh-rsa {self.keys[0]}", "rc": 0}

    result = self.run_script(responses)

    self.assertNotEqual(result.returncode, 0)
    self.assertIn("templ-prod-1: ssh-keyscan returned wrong key type(s): ssh-rsa", result.stderr)
    self.assert_previous_preserved(previous)

  def test_duplicate_endpoint_is_rejected_before_scan(self) -> None:
    previous = self.seed_known_hosts()
    self.write_inventory(endpoints=(ENDPOINTS[0], ENDPOINTS[0], ENDPOINTS[2]))

    result = self.run_script()

    self.assertNotEqual(result.returncode, 0)
    self.assertIn("duplicate public endpoints", result.stderr)
    self.assert_previous_preserved(previous)

  def test_duplicate_expected_key_is_rejected_before_scan(self) -> None:
    previous = self.seed_known_hosts()
    expected = tuple(fingerprint(item) for item in self.keys)
    self.write_inventory(fingerprints=(expected[0], expected[0], expected[2]))

    result = self.run_script()

    self.assertNotEqual(result.returncode, 0)
    self.assertIn("duplicate ED25519 host-key fingerprints", result.stderr)
    self.assert_previous_preserved(previous)

  def test_invalid_or_truncated_fingerprint_is_rejected_before_scan(self) -> None:
    previous = self.seed_known_hosts()
    expected = tuple(fingerprint(item) for item in self.keys)
    self.write_inventory(fingerprints=("SHA256:abc…xyz", expected[1], expected[2]))

    result = self.run_script()

    self.assertNotEqual(result.returncode, 0)
    self.assertIn("must be a complete console-verified SHA256 fingerprint", result.stderr)
    self.assert_previous_preserved(previous)

  def test_task_integrates_preflight_before_vault_and_playbook_mutation(self) -> None:
    taskfile = (ROOT / "taskfiles/wireguard.yml").read_text(encoding="utf-8")
    preflight = taskfile.index("scripts/prod-known-hosts.py")
    vault = taskfile.index("scripts/vault-prod-wireguard-ensure.sh")
    playbook = taskfile.index("playbooks/prod-wireguard-up.yml")
    self.assertLess(preflight, vault)
    self.assertLess(vault, playbook)
    self.assertNotIn("prod-known-hosts:", (ROOT / "Taskfile.yml").read_text(encoding="utf-8"))


if __name__ == "__main__":
  unittest.main()
