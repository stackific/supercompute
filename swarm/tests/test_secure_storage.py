from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/vault-swarm-secrets.py"
NODES = ("node-1", "node-2", "node-3")


class SecureStorageTest(unittest.TestCase):
  def setUp(self) -> None:
    self.temporary = tempfile.TemporaryDirectory()
    self.addCleanup(self.temporary.cleanup)
    self.root = Path(self.temporary.name)
    self.vault = self.root / "vault.yml"
    self.inventory = self.root / "hosts.yml"
    self.inventory.write_text(
      yaml.safe_dump(
        {
          "all": {
            "children": {
              "wireguard_nodes": {"hosts": {node: {} for node in NODES}},
            },
          },
        },
        sort_keys=False,
      ),
      encoding="utf-8",
    )

  def run_script(self) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
      [
        sys.executable,
        str(SCRIPT),
        "--vault",
        str(self.vault),
        "--inventory",
        str(self.inventory),
      ],
      cwd=ROOT,
      capture_output=True,
      check=False,
      text=True,
    )

  def test_vault_reconciliation_adds_distinct_per_node_secrets_once(self) -> None:
    self.vault.write_text("existing: value\n", encoding="utf-8")

    first = self.run_script()
    self.assertEqual(first.returncode, 0, first.stderr)
    self.assertEqual(first.stdout.strip(), "changed")
    document = yaml.safe_load(self.vault.read_text(encoding="utf-8"))
    self.assertGreaterEqual(len(document["vault_swarm_backup_restic_password"]), 32)
    passphrases = document["vault_encryption_at_rest_passphrases"]
    self.assertEqual(set(passphrases), set(NODES))
    self.assertEqual(len(set(passphrases.values())), len(NODES))
    self.assertTrue(all(len(value) >= 32 for value in passphrases.values()))

    second = self.run_script()
    self.assertEqual(second.returncode, 0, second.stderr)
    self.assertEqual(second.stdout.strip(), "verified")
    self.assertEqual(yaml.safe_load(self.vault.read_text(encoding="utf-8")), document)

  def test_vault_reconciliation_refuses_incomplete_node_key_map(self) -> None:
    self.vault.write_text(
      yaml.safe_dump(
        {
          "vault_swarm_backup_restic_password": "r" * 32,
          "vault_encryption_at_rest_passphrases": {NODES[0]: "s" * 32},
        }
      ),
      encoding="utf-8",
    )

    result = self.run_script()
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("must contain exactly these nodes", result.stderr)

  def test_swarm_up_unlocks_storage_before_starting_docker(self) -> None:
    playbook = (ROOT / "playbooks/swarm-up.yml").read_text(encoding="utf-8")
    self.assertLess(playbook.index("- secure_storage"), playbook.index("- swarm_engine"))
    self.assertIn("encryption_at_rest is boolean", playbook)

    tasks = (ROOT / "roles/secure_storage/tasks/enabled.yml").read_text(encoding="utf-8")
    ownership = (ROOT / "roles/secure_storage/tasks/main.yml").read_text(encoding="utf-8")
    self.assertIn("Refuse in-place encryption of existing plaintext data", tasks)
    self.assertIn("--source=custom_passphrase", tasks)
    self.assertIn("policy_version:2", tasks)
    self.assertIn("ExecStartPre=/usr/bin/test -f", tasks)
    self.assertNotIn("secure_storage_passphrase }}\n", tasks)
    self.assertIn("Require the exact project encryption ownership marker", ownership)
    self.assertIn("secure_storage_marker.stat.mode == '0600'", ownership)

  def test_business_data_path_convention_is_documented(self) -> None:
    storage = (ROOT / "docs/encrypted-at-rest.md").read_text(encoding="utf-8")
    self.assertIn("/srv/secure/<container-id>", storage)
    self.assertIn("Docker's ephemeral runtime container ID", storage)
    self.assertIn("backs up only `/var/lib/docker/swarm`, not `/srv/secure`", storage)


if __name__ == "__main__":
  unittest.main()
