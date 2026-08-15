from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LimaStatusTaskTest(unittest.TestCase):
  def test_public_lima_tasks_forward_only_the_template_local_provider(self) -> None:
    public_taskfile = (ROOT / "Taskfile.yml").read_text(encoding="utf-8")

    for name, next_name in (
      ("lima-up", "lima-status"),
      ("lima-status", "lima-destroy"),
      ("lima-destroy", "wg-up"),
    ):
      section = public_taskfile[
        public_taskfile.index(f"  {name}:"):public_taskfile.index(f"  {next_name}:")
      ]
      self.assertIn("- name: PROVIDER", section)
      self.assertIn("enum: [templ-local]", section)
      self.assertIn(f"task: lima:{name.removeprefix('lima-')}", section)
      self.assertIn('PROVIDER: "{{.PROVIDER}}"', section)

  def test_unrelated_tasks_retain_the_existing_default_provider(self) -> None:
    public_taskfile = (ROOT / "Taskfile.yml").read_text(encoding="utf-8")
    vault_taskfile = (ROOT / "taskfiles/vault.yml").read_text(encoding="utf-8")

    self.assertIn(
      'DEFAULT_PROVIDER: \'{{.PROVIDER | default "templ-local"}}\'',
      public_taskfile,
    )
    vault_init = public_taskfile[
      public_taskfile.index("  vault-init:"):public_taskfile.index("  vault-edit:")
    ]
    self.assertIn('PROVIDER: "{{.DEFAULT_PROVIDER}}"', vault_init)
    self.assertNotIn("PROVIDER | default", vault_taskfile)

  def test_internal_lima_tasks_reject_other_providers(self) -> None:
    internal_taskfile = (ROOT / "taskfiles/lima.yml").read_text(encoding="utf-8")

    for name, next_name in (("up", "status"), ("status", "destroy")):
      section = internal_taskfile[
        internal_taskfile.index(f"  {name}:"):internal_taskfile.index(f"  {next_name}:")
      ]
      self.assertIn('test "{{.PROVIDER}}" = "templ-local"', section)

    destroy = internal_taskfile[internal_taskfile.index("  destroy:"):]
    self.assertIn('test "{{.PROVIDER}}" = "templ-local"', destroy)

  def test_status_is_read_only_and_uses_the_project_lima_home(self) -> None:
    internal_taskfile = (ROOT / "taskfiles/lima.yml").read_text(encoding="utf-8")
    internal_status = internal_taskfile[
      internal_taskfile.index("  status:"):internal_taskfile.index("  destroy:")
    ]

    self.assertIn('scripts/lima-runtime-home.sh', internal_status)
    self.assertIn('LIMA_HOME="$(bash', internal_status)
    self.assertNotIn("limactl start", internal_status)
    self.assertNotIn("limactl delete", internal_status)


if __name__ == "__main__":
  unittest.main()
