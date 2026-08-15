from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class SwarmBaselineTest(unittest.TestCase):
  def test_public_provider_tasks_dispatch_to_internal_swarm_tasks(self) -> None:
    taskfile = (ROOT / "Taskfile.yml").read_text(encoding="utf-8")
    for name, next_task in (
      ("up", "swarm-down"),
      ("down", "swarm-status"),
      ("status", "garage-up"),
    ):
      section_start = taskfile.index(f"  swarm-{name}:")
      next_section = taskfile.index(f"  {next_task}:", section_start)
      section = taskfile[section_start:next_section]
      self.assertIn(f"task: swarm:{name}", section)
      self.assertIn('PROVIDER: "{{.PROVIDER}}"', section)

  def test_all_inventory_nodes_are_active_with_one_backup_workload_selector(self) -> None:
    for provider in ("templ-local", "templ-prod"):
      inventory = yaml.safe_load(
        (ROOT / f"inventories/{provider}/hosts.yml").read_text(encoding="utf-8")
      )
      hosts = inventory["all"]["children"]["wireguard_nodes"]["hosts"]
      self.assertEqual(len(hosts), 3)
      self.assertTrue(all(values["swarm_availability"] == "active" for values in hosts.values()))
      self.assertEqual(
        sum(values["swarm_run_on_backup"] is True for values in hosts.values()),
        1,
      )
      self.assertTrue(
        all(isinstance(values["swarm_run_on_backup"], bool) for values in hosts.values())
      )

  def test_docker_artifacts_are_sha256_pinned_for_both_architectures(self) -> None:
    defaults = yaml.safe_load(
      (ROOT / "roles/swarm_engine/defaults/main.yml").read_text(encoding="utf-8")
    )
    artifacts = defaults["swarm_docker_artifacts"]
    self.assertEqual(set(artifacts), {"amd64", "arm64"})
    for architecture, expected_suffix in (("amd64", "_amd64.deb"), ("arm64", "_arm64.deb")):
      self.assertEqual(
        [item["package"] for item in artifacts[architecture]],
        ["containerd.io", "docker-ce-cli", "docker-ce"],
      )
      for item in artifacts[architecture]:
        self.assertTrue(item["filename"].endswith(expected_suffix))
        self.assertRegex(item["sha256"], r"^[a-f0-9]{64}$")
    self.assertNotEqual(
      {item["sha256"] for item in artifacts["amd64"]},
      {item["sha256"] for item in artifacts["arm64"]},
    )

  def test_swarm_up_installs_the_gvisor_archive_extractor(self) -> None:
    defaults = yaml.safe_load(
      (ROOT / "roles/swarm_engine/defaults/main.yml").read_text(encoding="utf-8")
    )
    engine = (ROOT / "roles/swarm_engine/tasks/main.yml").read_text(encoding="utf-8")
    gvisor = (ROOT / "roles/swarm_gvisor/tasks/present.yml").read_text(encoding="utf-8")

    self.assertIn("bzip2", defaults["swarm_docker_runtime_dependencies"])
    self.assertIn("gvisor.tar.bz2", gvisor)
    self.assertLess(
      engine.index("Install missing Docker runtime dependencies"),
      engine.index("Install SHA256-pinned Docker artifacts"),
    )

  def test_swarm_up_downloads_only_artifacts_that_need_installation(self) -> None:
    docker = (ROOT / "roles/swarm_engine/tasks/install-artifact.yml").read_text(
      encoding="utf-8"
    )
    gvisor = (ROOT / "roles/swarm_gvisor/tasks/present.yml").read_text(encoding="utf-8")

    self.assertLess(docker.index("Read installed"), docker.index("Download pinned"))
    self.assertIn("swarm_docker_artifact_installed_version.rc != 0", docker)
    self.assertIn("swarm_docker_artifact_installed_version.stdout !=", docker)
    self.assertLess(
      gvisor.index("Read the existing gVisor version"),
      gvisor.index("Download the SHA512-pinned gVisor release"),
    )
    self.assertIn("swarm_gvisor_install_required", gvisor)
    self.assertIn("when: swarm_gvisor_install_required", gvisor)

  def test_swarm_lifecycle_stays_on_wireguard_and_preserves_docker_on_down(self) -> None:
    up = (ROOT / "playbooks/swarm-up.yml").read_text(encoding="utf-8")
    down = (ROOT / "playbooks/swarm-down.yml").read_text(encoding="utf-8")
    status = (ROOT / "playbooks/swarm-status.yml").read_text(encoding="utf-8")

    self.assertIn("--advertise-addr", up)
    self.assertIn("--data-path-addr", up)
    self.assertIn("swarm_node_address", up)
    self.assertIn("{{if .Swarm.Cluster}}{{.Swarm.Cluster.ID}}{{end}}", up)
    self.assertNotIn("|{{.Swarm.Cluster.ID}}|", up)
    self.assertIn("join-token, --quiet, manager", up)
    self.assertIn("swarm_availability_effective", up)
    self.assertIn("swarm_gvisor", up)
    self.assertIn("docker, swarm, leave, --force", down)
    self.assertIn("swarm_gvisor", down)
    self.assertIn("swarm_gvisor_state: absent", down)
    self.assertNotIn("apt", down)
    self.assertNotIn("wg-quick", down)
    self.assertIn("docker, node, ls", status)
    self.assertNotIn("node, update", status)

  def test_gvisor_is_pinned_for_both_architectures_and_owned_by_swarm_lifecycle(self) -> None:
    defaults = yaml.safe_load(
      (ROOT / "roles/swarm_gvisor/defaults/main.yml").read_text(encoding="utf-8")
    )
    present = (ROOT / "roles/swarm_gvisor/tasks/present.yml").read_text(encoding="utf-8")
    absent = (ROOT / "roles/swarm_gvisor/tasks/absent.yml").read_text(encoding="utf-8")
    taskfile = (ROOT / "Taskfile.yml").read_text(encoding="utf-8")

    self.assertEqual(defaults["swarm_gvisor_release"], "20260810.0")
    self.assertEqual(set(defaults["swarm_gvisor_artifacts"]), {"x86_64", "aarch64"})
    for artifact in defaults["swarm_gvisor_artifacts"].values():
      self.assertRegex(artifact["sha512"], r"^[a-f0-9]{128}$")
    self.assertEqual(defaults["swarm_gvisor_docker_config"]["default-runtime"], "runsc")
    self.assertEqual(
      defaults["swarm_gvisor_docker_config"]["runtimes"]["runsc"]["runtimeArgs"],
      ["--network=sandbox"],
    )
    self.assertEqual(
      defaults["swarm_gvisor_legacy_docker_configs"],
      [
        {
          "default-runtime": "runsc",
          "runtimes": {
            "runsc": {"path": "{{ swarm_gvisor_install_dir }}/runsc"},
          },
        },
      ],
    )
    self.assertIn("Require the isolated gVisor netstack runtime policy", present)
    self.assertIn("['--network=sandbox']", present)
    self.assertIn("swarm_gvisor_legacy_docker_configs", present)
    self.assertIn("swarm_gvisor_legacy_docker_configs", absent)
    self.assertIn("Refuse to overwrite Docker configuration not owned by this baseline", present)
    self.assertIn("Refuse to remove Docker configuration not owned by this baseline", absent)
    self.assertIn("swarm_gvisor_restored_docker_runtime.stdout == 'runc'", absent)
    self.assertNotIn("  gvisor-up:", taskfile)
    self.assertNotIn("  gvisor-down:", taskfile)

  def test_provider_verify_runs_and_cleans_up_a_pinned_gvisor_job(self) -> None:
    taskfile = (ROOT / "Taskfile.yml").read_text(encoding="utf-8")
    internal = (ROOT / "taskfiles/verify.yml").read_text(encoding="utf-8")
    playbook = (ROOT / "playbooks/verify.yml").read_text(encoding="utf-8")
    defaults = yaml.safe_load(
      (ROOT / "roles/swarm_gvisor/defaults/main.yml").read_text(encoding="utf-8")
    )

    section_start = taskfile.index("  verify:", taskfile.index("tasks:"))
    section = taskfile[section_start:taskfile.index("  garage-up:", section_start)]
    self.assertIn("task: verify:baseline", section)
    self.assertIn('PROVIDER: "{{.PROVIDER}}"', section)
    self.assertIn('"{{.PROVIDER}}" --syntax-check playbooks/verify.yml', internal)
    self.assertIn('"{{.PROVIDER}}" playbooks/verify.yml', internal)

    image = defaults["swarm_gvisor_verify_image"]
    self.assertRegex(
      image,
      r"^docker\.io/library/alpine:[0-9.]+@sha256:[a-f0-9]{64}$",
    )
    self.assertIn("--mode", playbook)
    self.assertIn("global-job", playbook)
    self.assertIn("node.labels.run_on_backup==true", playbook)
    self.assertIn("dmesg | grep -qi gvisor", playbook)
    self.assertIn("{{ deployment_name }}_GVISOR_OK", playbook)
    self.assertIn("always:", playbook)
    self.assertIn("docker, service, rm", playbook)
    self.assertIn("swarm_verify_service_absent.rc != 0", playbook)

  def test_provider_verify_checks_the_baseline_without_reconciling_it(self) -> None:
    playbook = (ROOT / "playbooks/verify.yml").read_text(encoding="utf-8")

    self.assertIn("dpkg-query", playbook)
    self.assertIn("wg-quick@{{ swarm_verify_wireguard_interface }}.service", playbook)
    self.assertIn("manual_wireguard", playbook)
    self.assertIn("swarm_gvisor_docker_config", playbook)
    self.assertIn("Require the exact gVisor netstack Docker runtime configuration", playbook)
    self.assertIn("['--network=sandbox']", playbook)
    self.assertIn("swarm_verify_docker_fields[6] == 'runsc'", playbook)
    self.assertIn("docker", playbook)
    self.assertIn("node", playbook)
    self.assertIn("inspect", playbook)
    self.assertIn("swarm_node_address ~ ':2377'", playbook)
    self.assertNotIn("docker, node, update", playbook)
    self.assertNotIn("docker, swarm, init", playbook)
    self.assertNotIn("docker, swarm, join", playbook)

  def test_requested_setup_guides_document_swarm_commands(self) -> None:
    for guide in ("setup-templ-local.md", "setup-templ-prod.md"):
      content = (ROOT / f"docs/{guide}").read_text(encoding="utf-8")
      self.assertIn("task swarm-up", content)
      self.assertIn("task swarm-down", content)
      self.assertIn("task swarm-status", content)
      self.assertIn("task verify", content)


if __name__ == "__main__":
  unittest.main()
