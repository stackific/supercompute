from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/reset.sh"


class ProductionResetTest(unittest.TestCase):
  def setUp(self) -> None:
    self.temporary = tempfile.TemporaryDirectory()
    self.addCleanup(self.temporary.cleanup)
    self.project = Path(self.temporary.name) / "project"
    self.vault = self.project / "inventories/templ-prod/group_vars/all/vault.yml"
    self.password = self.project / "inventories/templ-prod/.vault-pass"
    self.controller_config = self.project / ".state/templ-prod/wireguard/scwg0.conf"
    self.known_hosts = self.project / ".state/templ-prod/known_hosts"
    for path in (self.vault, self.password, self.controller_config, self.known_hosts):
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_text(f"preserve-or-remove:{path.name}\n", encoding="utf-8")
      path.chmod(0o600)
    self.environment = os.environ.copy()
    self.environment.update(
      {
        "DOCKER_SWARM_RESET_TEST_MODE": "1",
        "DOCKER_SWARM_RESET_TEST_PROJECT_DIR": str(self.project),
      }
    )

  def run_reset(self, confirmation: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
      ["bash", str(SCRIPT), "templ-prod", confirmation],
      cwd=ROOT,
      env=self.environment,
      text=True,
      capture_output=True,
      check=False,
    )

  def test_reset_templ_prod_removes_only_the_provider_vault_pair(self) -> None:
    config = self.controller_config.read_bytes()
    known_hosts = self.known_hosts.read_bytes()

    result = self.run_reset("reset-templ-prod")

    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn("only the provider Vault and Vault password were removed", result.stdout)
    self.assertFalse(self.vault.exists())
    self.assertFalse(self.password.exists())
    self.assertEqual(self.controller_config.read_bytes(), config)
    self.assertEqual(self.known_hosts.read_bytes(), known_hosts)

  def test_wrong_confirmation_preserves_every_file(self) -> None:
    before = {
      path: path.read_bytes()
      for path in (self.vault, self.password, self.controller_config, self.known_hosts)
    }

    result = self.run_reset("reset-templ-local")

    self.assertNotEqual(result.returncode, 0)
    self.assertIn("CONFIRM=reset-templ-prod", result.stderr)
    for path, content in before.items():
      self.assertEqual(path.read_bytes(), content)

  def test_public_task_exposes_provider_aware_reset(self) -> None:
    taskfile = (ROOT / "Taskfile.yml").read_text(encoding="utf-8")
    reset = taskfile[taskfile.index("  reset:", taskfile.index("tasks:")):taskfile.index("  lima-up:")]
    self.assertIn('test "{{.PROVIDER}}" = "templ-prod"', reset)
    self.assertIn('PROVIDER: "{{.PROVIDER}}"', reset)
    self.assertIn('CONFIRM: "{{.CONFIRM}}"', reset)


if __name__ == "__main__":
  unittest.main()
