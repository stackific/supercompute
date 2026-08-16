from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/garage-destroy-owned.py"
SPEC = importlib.util.spec_from_file_location("garage_destroy_owned", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class GarageStandaloneTest(unittest.TestCase):
  def test_garage_uses_stable_global_docker_names(self) -> None:
    variables = yaml.safe_load(
      (ROOT / "inventories/templ-local/group_vars/all/main.yml").read_text(
        encoding="utf-8"
      )
    )

    self.assertEqual(variables["garage_container"], "swarm-garage")
    self.assertEqual(variables["garage_network"], "swarm-garage")
    self.assertEqual(variables["garage_metadata_volume"], "swarm-garage-metadata")
    self.assertEqual(variables["garage_data_volume"], "swarm-garage-data")

  def test_public_garage_tasks_ignore_provider_selection(self) -> None:
    taskfile = (ROOT / "Taskfile.yml").read_text(encoding="utf-8")
    names = ("garage-up", "garage-down", "garage-destroy", "garage-status", "garage-credentials")
    for index, name in enumerate(names):
      start = taskfile.index(f"  {name}:")
      end = taskfile.index(f"  {names[index + 1]}:") if index + 1 < len(names) else taskfile.index("  syntax-check:")
      section = taskfile[start:end]
      self.assertIn("PROVIDER: templ-local", section)
      self.assertNotIn("DEFAULT_PROVIDER", section)

    internal = (ROOT / "taskfiles/garage.yml").read_text(encoding="utf-8")
    controller = (ROOT / "scripts/ansible-playbook.sh").read_text(encoding="utf-8")
    self.assertEqual(internal.count("DOCKER_SWARM_STANDALONE_GARAGE=1"), 4)
    self.assertIn('"${DOCKER_SWARM_STANDALONE_GARAGE:-0}" != "1"', controller)

  def test_destroy_recognizes_stable_and_matching_legacy_ownership(self) -> None:
    stable = {
      "Name": "/swarm-garage",
      "Config": {"Labels": {MODULE.MANAGED_LABEL: "true"}},
    }
    legacy = {
      "Name": "/sc-swarm2-garage",
      "Config": {
        "Labels": {"com.stackific.sc-swarm2.garage-managed": "true"}
      },
    }
    unrelated = {
      "Name": "/someone-garage",
      "Config": {"Labels": {"com.example.managed": "true"}},
    }

    self.assertTrue(MODULE.is_owned("container", stable))
    self.assertTrue(MODULE.is_owned("container", legacy))
    self.assertTrue(
      MODULE.is_owned(
        "network",
        {
          "Name": "sc-swarm2-garage",
          "Labels": {"com.stackific.sc-swarm2.garage-managed": "true"},
        },
      )
    )
    for name in ("sc-swarm2-garage-data", "sc-swarm2-garage-metadata"):
      self.assertTrue(
        MODULE.is_owned(
          "volume",
          {
            "Name": name,
            "Labels": {"com.stackific.sc-swarm2.garage-managed": "true"},
          },
        )
      )
    self.assertFalse(MODULE.is_owned("container", unrelated))

    role = (ROOT / "roles/garage/tasks/main.yml").read_text(encoding="utf-8")
    self.assertIn("scripts/garage-destroy-owned.py", role)
    self.assertIn("ansible_playbook_python", role)

  def test_destroy_refuses_an_unmanaged_stable_name(self) -> None:
    with self.assertRaises(MODULE.OwnershipError):
      MODULE.is_owned("network", {"Name": "swarm-garage", "Labels": {}})

  def test_documented_garage_commands_are_standalone(self) -> None:
    documentation = "\n".join(
      path.read_text(encoding="utf-8")
      for path in (ROOT / "README.md", ROOT / "docs/setup-templ-local.md")
    )
    self.assertNotRegex(documentation, r"garage-[a-z-]+ PROVIDER=")


if __name__ == "__main__":
  unittest.main()
