from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class LimaRuntimeHomeTest(unittest.TestCase):
  def test_ansible_runtime_home_uses_the_wrappers_short_runtime_alias(self) -> None:
    variables = yaml.safe_load(
      (ROOT / "inventories/templ-local/group_vars/all/main.yml").read_text(
        encoding="utf-8"
      )
    )

    self.assertEqual(
      variables["lima_runtime_home"],
      "{{ lookup('ansible.builtin.env', 'LIMA_HOME') }}",
    )
    self.assertEqual(variables["lima_home_dir"], "{{ lima_runtime_home }}")

  def test_runtime_home_is_short_persistent_and_provider_scoped(self) -> None:
    helper = (ROOT / "scripts/lima-runtime-home.sh").read_text(encoding="utf-8")
    controller = (ROOT / "scripts/ansible-playbook.sh").read_text(encoding="utf-8")

    self.assertIn('lima_system_home="${HOME}/.lima"', helper)
    self.assertIn('lima_provider_home="${lima_system_home}/.${provider_name}"', helper)
    self.assertIn('provider_name="$1"', helper)
    self.assertIn('provider_name}" != "templ-local"', helper)
    self.assertNotIn("/tmp/", helper)
    self.assertNotIn("/bin/ln", helper)
    self.assertIn(
      'LIMA_HOME="$(bash "${project_dir}/scripts/lima-runtime-home.sh" "${provider_name}")"',
      controller,
    )

  def test_every_local_lima_play_uses_the_inventory_runtime_home(self) -> None:
    for relative_path in (
      "playbooks/lima-up.yml",
      "playbooks/lima-destroy.yml",
      "playbooks/verify-before.yml",
      "playbooks/verify-after.yml",
      "playbooks/wireguard-up.yml",
      "playbooks/wireguard-remove.yml",
    ):
      content = (ROOT / relative_path).read_text(encoding="utf-8")
      self.assertIn('LIMA_HOME: "{{ lima_runtime_home }}"', content, relative_path)

  def test_ansible_controller_changes_to_the_discovered_project_root(self) -> None:
    controller = (ROOT / "scripts/ansible-playbook.sh").read_text(encoding="utf-8")

    discover = 'project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"'
    change_directory = 'cd "${project_dir}"'
    execute = "exec uv run --locked ansible-playbook"
    self.assertLess(controller.index(discover), controller.index(change_directory))
    self.assertLess(controller.index(change_directory), controller.index(execute))

  def test_reset_uses_and_removes_only_the_verified_runtime_home(self) -> None:
    reset = (ROOT / "scripts/reset.sh").read_text(encoding="utf-8")

    self.assertIn(
      'lima_runtime_home="$(bash "${repository_dir}/scripts/lima-runtime-home.sh" "${requested_provider}")"',
      reset,
    )
    self.assertIn('lima_home_dir="${lima_runtime_home}"', reset)
    self.assertIn('LIMA_HOME="${lima_runtime_home}" limactl list', reset)
    self.assertIn('scripts/lima-runtime-home.sh" "${requested_provider}" remove', reset)

  def test_wireguard_ssh_uses_the_provider_scoped_lima_identity(self) -> None:
    wireguard_ssh = (ROOT / "scripts/wg-ssh.sh").read_text(encoding="utf-8")

    self.assertIn(
      'lima_home="$(bash "${project_dir}/scripts/lima-runtime-home.sh" "${provider_name}")"',
      wireguard_ssh,
    )
    self.assertIn('lima_identity="${lima_home}/_config/user"', wireguard_ssh)
    self.assertNotIn('${project_dir}/.l/_config/user', wireguard_ssh)


if __name__ == "__main__":
  unittest.main()
