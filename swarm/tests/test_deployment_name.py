from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class DeploymentNameTest(unittest.TestCase):
  def test_single_customer_deployment_name_is_loaded_by_the_ansible_wrapper(self) -> None:
    deployment = yaml.safe_load((ROOT / "deployment.yml").read_text(encoding="utf-8"))
    self.assertEqual(set(deployment), {"deployment_name", "encryption_at_rest"})
    self.assertRegex(deployment["deployment_name"], r"^[a-z][a-z0-9-]{0,31}$")
    self.assertIs(deployment["encryption_at_rest"], True)

    wrapper = (ROOT / "scripts/ansible-playbook.sh").read_text(encoding="utf-8")
    self.assertIn('deployment_vars="${project_dir}/deployment.yml"', wrapper)
    self.assertIn('--extra-vars "@${deployment_vars}"', wrapper)
    self.assertIn('--extra-vars "inventory_slug=${provider_name}"', wrapper)

  def test_backup_prefixes_derive_the_selected_inventory_slug(self) -> None:
    for inventory in ("templ-local", "templ-prod"):
      values = (ROOT / f"inventories/{inventory}/group_vars/all/main.yml").read_text(
        encoding="utf-8"
      )
      self.assertIn(
        'swarm_backup_object_prefix: "{{ deployment_name }}/{{ inventory_slug }}/swarm-state/v1"',
        values,
      )
      self.assertNotIn(f"/{inventory}/swarm-state", values)

  def test_deployable_configuration_does_not_hardcode_the_default_name(self) -> None:
    roots = (
      ROOT / "inventories",
      ROOT / "playbooks",
      ROOT / "roles",
    )
    deployment_name = yaml.safe_load(
      (ROOT / "deployment.yml").read_text(encoding="utf-8")
    )["deployment_name"]
    offenders = []
    for directory in roots:
      for path in directory.rglob("*"):
        if not path.is_file():
          continue
        try:
          content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
          continue
        if deployment_name in content:
          offenders.append(str(path.relative_to(ROOT)))
    self.assertEqual(offenders, [])


if __name__ == "__main__":
  unittest.main()
