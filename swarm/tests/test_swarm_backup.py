from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class SwarmBackupTest(unittest.TestCase):
  def setUp(self) -> None:
    self.defaults = yaml.safe_load(
      (ROOT / "roles/swarm_backup/defaults/main.yml").read_text(encoding="utf-8")
    )
    self.present = (ROOT / "roles/swarm_backup/tasks/present.yml").read_text(encoding="utf-8")
    self.absent = (ROOT / "roles/swarm_backup/tasks/absent.yml").read_text(encoding="utf-8")
    self.runner = (ROOT / "roles/swarm_backup/files/swarm-backup-run").read_text(
      encoding="utf-8"
    )
    self.timer = (ROOT / "roles/swarm_backup/templates/swarm-backup.timer.j2").read_text(
      encoding="utf-8"
    )
    self.service = (ROOT / "roles/swarm_backup/templates/swarm-backup.service.j2").read_text(
      encoding="utf-8"
    )

  def test_each_inventory_has_three_active_managers_and_one_backup_label(self) -> None:
    for provider in ("templ-local", "templ-prod"):
      inventory = yaml.safe_load(
        (ROOT / f"inventories/{provider}/hosts.yml").read_text(encoding="utf-8")
      )
      hosts = inventory["all"]["children"]["wireguard_nodes"]["hosts"]
      selected = [name for name, values in hosts.items() if values["swarm_run_on_backup"]]
      self.assertEqual(len(selected), 1)
      self.assertTrue(all(values["swarm_availability"] == "active" for values in hosts.values()))
      self.assertTrue(
        all(isinstance(values["swarm_run_on_backup"], bool) for values in hosts.values())
      )

  def test_schedule_and_retention_are_fixed_to_the_requested_policy(self) -> None:
    self.assertEqual(self.defaults["swarm_backup_timer_interval_seconds"], 21600)
    self.assertEqual(self.defaults["swarm_backup_retention_days"], 30)
    self.assertIn("OnActiveSec={{ swarm_backup_timer_interval_seconds }}s", self.timer)
    self.assertIn("OnUnitInactiveSec={{ swarm_backup_timer_interval_seconds }}s", self.timer)
    self.assertIn("swarm_backup_timer_interval_seconds | int == 21600", self.present)
    self.assertIn("swarm_backup_retention_days | int == 30", self.present)
    self.assertIn('f"{config[\'retention_days\']}d"', self.runner)
    self.assertIn('"--keep-within"', self.runner)
    self.assertIn('"--prune"', self.runner)
    forget = self.runner.partition('"forget",')[2].partition("print(")[0]
    self.assertNotIn('"--host"', forget)

  def test_restic_is_sha256_pinned_for_arm64_and_amd64(self) -> None:
    self.assertEqual(self.defaults["swarm_backup_restic_version"], "0.19.1")
    artifacts = self.defaults["swarm_backup_restic_artifacts"]
    self.assertEqual(set(artifacts), {"x86_64", "aarch64"})
    for item in artifacts.values():
      self.assertRegex(item["sha256"], r"^[a-f0-9]{64}$")
      self.assertTrue(item["filename"].endswith(".bz2"))
    self.assertIn("Download the SHA256-pinned Restic artifact only when needed", self.present)
    self.assertIn("when: swarm_backup_restic_install_required", self.present)

  def test_runner_validates_label_identity_and_refuses_standalone_containers(self) -> None:
    create = self.runner.partition("def create_backup")[2].partition("def main")[0]
    self.assertLess(
      create.index('require_healthy_quorum(config, "Active")'),
      create.index("capture_cold_archive"),
    )
    self.assertLess(create.index("require_no_standalone_containers()"), create.index("capture_cold_archive"))
    capture = self.runner.partition("def capture_cold_archive")[2].partition(
      "def wait_for_healthy_quorum"
    )[0]
    self.assertLess(capture.index("require_empty_manager()"), capture.index('"stop", "docker.service"'))
    self.assertLess(capture.index('"stop", "docker.socket"'), capture.index('"stop", "docker.service"'))
    self.assertIn('node["RunOnBackup"] == "true"', self.runner)
    self.assertIn('labels.get("com.docker.swarm.task.id")', self.runner)
    self.assertIn('selected[0]["ID"] == labeled[0]["ID"]', self.runner)
    self.assertIn('len(nodes) == 3', self.runner)

  def test_runner_temporarily_drains_and_restores_active_without_rejoining(self) -> None:
    create = self.runner.partition("def create_backup")[2].partition("def main")[0]
    self.assertLess(
      create.index('set_manager_availability(local_node_id, "drain")'),
      create.index("capture_cold_archive"),
    )
    self.assertIn("finally:", create)
    self.assertIn("restore_active_availability(config)", create)
    self.assertIn('wait_for_healthy_quorum(config, "Drain")', create)
    restore = self.runner.partition("def restore_active_availability")[2].partition(
      "def create_backup"
    )[0]
    self.assertIn('set_manager_availability(local_node_id, "active")', restore)
    self.assertIn('wait_for_healthy_quorum(config, "Active")', restore)
    self.assertIn("restart_docker()", restore)
    self.assertNotIn("swarm join", self.runner)
    self.assertIn("ExecStopPost=/usr/bin/systemctl start docker.socket docker.service", self.service)
    self.assertIn(
      "ExecStopPost={{ swarm_backup_runner_path }} --config {{ swarm_backup_config_path }} --restore-active",
      self.service,
    )
    self.assertIn("def restore_active_availability", self.runner)
    self.assertIn('parser.add_argument("--restore-active", action="store_true")', self.runner)

  def test_only_the_labeled_node_owns_the_timer_and_down_preserves_s3(self) -> None:
    up = (ROOT / "playbooks/swarm-up.yml").read_text(encoding="utf-8")
    down = (ROOT / "playbooks/swarm-down.yml").read_text(encoding="utf-8")
    self.assertIn("exactly one", up)
    self.assertIn("swarm_run_on_backup=true", up)
    self.assertIn("run_on_backup=", up)
    self.assertIn("Install the backup timer only on the labeled active manager", up)
    self.assertIn("swarm_backup_state", up)
    self.assertLess(
      up.index("Remove backup ownership from managers without the backup label"),
      up.index("Install the backup timer only on the labeled active manager"),
    )
    self.assertIn("Remove the project backup timer before leaving Swarm", down)
    self.assertNotIn("RESTIC_REPOSITORY", self.absent)
    self.assertNotIn("forget", self.absent)

  def test_runner_is_valid_python(self) -> None:
    compile(self.runner, "swarm-backup-run", "exec")

  def test_provider_guides_document_storage_and_cold_backup_boundaries(self) -> None:
    local = (ROOT / "docs/setup-templ-local.md").read_text(encoding="utf-8")
    templ_prod = (ROOT / "docs/setup-templ-prod.md").read_text(encoding="utf-8")
    local_vars = yaml.safe_load(
      (ROOT / "inventories/templ-local/group_vars/all/main.yml").read_text(encoding="utf-8")
    )
    for guide in (local, templ_prod):
      self.assertIn("Every six hours", guide)
      self.assertIn("/var/lib/docker/swarm", guide)
      self.assertIn("30-day", guide)
      self.assertIn("task swarm-status", guide)
      self.assertIn("node.labels.run_on_backup == true", guide)
      self.assertIn("node.labels.run_on_backup != true", guide)
    self.assertIn("Garage", local)
    self.assertIn("host.lima.internal", local)
    self.assertEqual(
      local_vars["swarm_backup_s3_endpoint"],
      "http://host.lima.internal:{{ garage_s3_host_port }}",
    )
    self.assertIn("Cloudflare R2", templ_prod)
    self.assertIn("vault_swarm_backup_s3_access_key", templ_prod)


if __name__ == "__main__":
  unittest.main()
