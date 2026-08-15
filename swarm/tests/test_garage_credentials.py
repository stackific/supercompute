from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class GarageCredentialsTest(unittest.TestCase):
  def test_prints_implemented_controller_endpoint_and_vault_values(self) -> None:
    deployment = yaml.safe_load((ROOT / "deployment.yml").read_text(encoding="utf-8"))
    expected_bucket = f'{deployment["deployment_name"]}-backups'
    with tempfile.TemporaryDirectory() as temporary_directory:
      test_root = Path(temporary_directory)
      project_dir = test_root / "project"
      bin_dir = test_root / "bin"
      vault_dir = project_dir / "inventories/templ-local/group_vars/all"
      vault_dir.mkdir(parents=True)
      bin_dir.mkdir()
      (vault_dir / "vault.yml").touch()
      (project_dir / "inventories/templ-local/.vault-pass").write_text(
        "test-password\n", encoding="utf-8"
      )

      fake_uv = bin_dir / "uv"
      fake_uv.write_text(
        textwrap.dedent(
          """
          #!/usr/bin/env bash
          set -Eeuo pipefail
          [[ "${1:-}" == "run" && "${2:-}" == "--locked" ]]
          printf '%s\n' \
            'vault_garage_access_key: test-access-key' \
            'vault_garage_secret_key: test-secret-key'
          """
        ).lstrip(),
        encoding="utf-8",
      )
      fake_uv.chmod(0o700)

      environment = os.environ.copy()
      environment.update(
        {
          "PATH": f"{bin_dir}:{environment['PATH']}",
          "DOCKER_SWARM_GARAGE_CREDENTIALS_TEST_MODE": "1",
          "DOCKER_SWARM_GARAGE_CREDENTIALS_TEST_PROJECT_DIR": str(project_dir),
        }
      )
      result = subprocess.run(
        ["bash", str(ROOT / "scripts/vault-garage-credentials.sh"), "templ-local"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
      )

    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(
      result.stdout.splitlines(),
      [
        'export AWS_ENDPOINT_URL="http://127.0.0.1:3901"',
        'export AWS_DEFAULT_REGION="garage"',
        'export AWS_ACCESS_KEY_ID="test-access-key"',
        'export AWS_SECRET_ACCESS_KEY="test-secret-key"',
        f'export GARAGE_BUCKET="{expected_bucket}"',
      ],
    )

  def test_rejects_test_path_override_without_test_mode(self) -> None:
    environment = os.environ.copy()
    environment["DOCKER_SWARM_GARAGE_CREDENTIALS_TEST_PROJECT_DIR"] = "/tmp/not-used"
    environment.pop("DOCKER_SWARM_GARAGE_CREDENTIALS_TEST_MODE", None)

    result = subprocess.run(
      ["bash", str(ROOT / "scripts/vault-garage-credentials.sh"), "templ-local"],
      cwd=ROOT,
      env=environment,
      text=True,
      capture_output=True,
      check=False,
    )

    self.assertEqual(result.returncode, 2)
    self.assertIn("require DOCKER_SWARM_GARAGE_CREDENTIALS_TEST_MODE=1", result.stderr)


if __name__ == "__main__":
  unittest.main()
