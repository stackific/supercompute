from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LimaLockdownStartupTest(unittest.TestCase):
  def setUp(self) -> None:
    self.unit = (
      ROOT / "roles/wireguard_controller/templates/manual-wg-firewall.service.j2"
    ).read_text(encoding="utf-8")
    self.gate = (
      ROOT / "roles/wireguard_controller/files/manual-wg-firewall-wait"
    ).read_text(encoding="utf-8")
    self.policy = (
      ROOT / "roles/wireguard_controller/templates/manual-wireguard-lockdown.nft.j2"
    ).read_text(encoding="utf-8")
    self.lima = (ROOT / "roles/lima/tasks/main.yml").read_text(encoding="utf-8")
    self.controller = (
      ROOT / "roles/wireguard_controller/tasks/main.yml"
    ).read_text(encoding="utf-8")
    self.after_guest = (
      ROOT / "roles/wireguard_verify/tasks/after-guest.yml"
    ).read_text(encoding="utf-8")
    self.lima_template = (
      ROOT / "roles/lima/templates/lima.yaml.j2"
    ).read_text(encoding="utf-8")

  def test_firewall_gate_does_not_block_lima_boot_and_always_applies_policy(self) -> None:
    self.assertIn("Type=simple", self.unit)
    self.assertIn("ExecStart={{ wireguard_firewall_wait_path }}", self.unit)
    self.assertNotIn("ExecStartPre", self.unit)
    self.assertIn("apply_lockdown", self.gate)
    self.assertIn("fail_closed_on_exit", self.gate)
    self.assertIn("applying fail-closed lockdown", self.gate)
    self.assertIn("exec /usr/bin/sleep infinity", self.gate)

  def test_gate_accepts_only_the_expected_recent_controller_handshake(self) -> None:
    self.assertIn('controller_cidr="${controller_address}/32"', self.gate)
    self.assertIn('wg show "${interface}" allowed-ips', self.gate)
    self.assertIn('wg show "${interface}" latest-handshakes', self.gate)
    self.assertIn('$2 == expected', self.gate)
    self.assertIn('$1 == expected', self.gate)
    self.assertIn('$(( now - latest_handshake )) -ge 0', self.gate)
    self.assertIn('$(( now - latest_handshake )) -le 60', self.gate)

  def test_existing_bootstrap_ssh_can_finish_but_new_non_wg_ssh_is_dropped(self) -> None:
    self.assertLess(
      self.policy.index(
        'iifname "eth0" ip saddr 192.168.104.0/24 tcp dport 22 ct state established accept'
      ),
      self.policy.index("tcp dport 22 drop"),
    )
    self.assertGreater(
      self.policy.index("ct state established,related accept"),
      self.policy.index("tcp dport 22 drop"),
    )
    self.assertLess(
      self.policy.index('iifname "wg0" ip saddr {{ wireguard_macos_address }} tcp dport 22 accept'),
      self.policy.index("tcp dport 22 drop"),
    )

  def test_lima_existing_instance_checks_are_host_side(self) -> None:
    self.assertIn("Wait for each pre-existing Lima WireGuard UDP forward", self.lima)
    self.assertIn('"-iUDP:{{ item.wg_host_port }}"', self.lima)
    forward_wait = self.lima[
      self.lima.index("Wait for each pre-existing Lima WireGuard UDP forward"):
      self.lima.index("Read the actual Ubuntu release and architecture from each new template-local guest")
    ]
    self.assertIn("item.name in lima_instance_names", forward_wait)
    self.assertIn("lima_existing_controller_wireguard_config.stat.exists", forward_wait)
    guest_read = self.lima[
      self.lima.index("Read the actual Ubuntu release and architecture from each new template-local guest"):
      self.lima.index("Require Ubuntu 26.04 Resolute ARM64 inside every new template-local guest")
    ]
    self.assertIn("item.name not in lima_instance_names", guest_read)
    self.assertNotIn("lima_lifecycle == 'verify'", guest_read)

  def test_lima_message_is_top_level_not_a_port_forward_property(self) -> None:
    ignored_ports = self.lima_template[
      self.lima_template.index("  - guestPortRange: [1, 65535]"):
    ]
    self.assertIn("\nmessage: docker-swarm owned template-local VM", ignored_ports)
    self.assertNotIn("\n    message:", ignored_ports)

  def test_ubuntu_2604_first_boot_uses_limas_netplan_workaround(self) -> None:
    self.assertIn('internal_netplanOptional: "true"', self.lima_template)
    self.assertIn('.param.internal_netplanOptional == "true"', self.lima)

  def test_guest_os_contract_moves_to_the_wireguard_path(self) -> None:
    self.assertIn("Read the Ubuntu release and architecture through WireGuard", self.after_guest)
    self.assertIn("wireguard_verify_guest_os_contract", self.after_guest)
    self.assertIn("node_ubuntu_version", self.after_guest)
    self.assertIn("node_host_architecture", self.after_guest)

  def test_existing_install_recovers_only_through_wireguard(self) -> None:
    wait = "Wait for existing Lima WireGuard UDP forwards before controller recovery"
    require = "Refuse controller recovery from legacy locked guests"
    restore = "Restore an existing macOS WireGuard interface before any Lima access"
    probe = "Test existing WireGuard management paths before using Lima"
    refuse = "Refuse unsafe ordinary Lima fallback for an existing WireGuard installation"
    bootstrap = "Bootstrap WireGuard into each VM through ordinary Lima access"
    self.assertLess(self.controller.index(wait), self.controller.index(restore))
    self.assertLess(self.controller.index(require), self.controller.index(restore))
    self.assertLess(self.controller.index(restore), self.controller.index(probe))
    self.assertLess(self.controller.index(probe), self.controller.index(refuse))
    self.assertLess(self.controller.index(refuse), self.controller.index(bootstrap))

    probe_task = self.controller[
      self.controller.index(probe):self.controller.index(
        "Decide whether WireGuard is already a healthy management path"
      )
    ]
    self.assertIn("until: wireguard_controller_existing_paths.rc == 0", probe_task)
    self.assertIn("retries: 30", probe_task)

    refuse_task = self.controller[
      self.controller.index(refuse):self.controller.index(
        "Require encrypted WireGuard keys from Ansible Vault"
      )
    ]
    self.assertIn("wireguard_controller_existing_macos_wireguard_config.stat.exists", refuse_task)
    self.assertIn("wireguard_controller_overlay_healthy", refuse_task)
    self.assertIn("wireguard_controller_rebootstrap_required", refuse_task)

    bootstrap_task = self.controller[self.controller.index(bootstrap):]
    self.assertIn(
      "not wireguard_controller_existing_macos_wireguard_config.stat.exists",
      bootstrap_task,
    )
    self.assertIn("wireguard_controller_rebootstrap_required", bootstrap_task)

  def test_first_install_waits_for_udp_only_after_wireguard_bootstrap(self) -> None:
    bootstrap = "Bootstrap WireGuard into each VM through ordinary Lima access"
    wait = "Wait for Lima's UDP forwards after first WireGuard bootstrap"
    self.assertLess(self.controller.index(bootstrap), self.controller.index(wait))
    wait_task = self.controller[self.controller.index(wait):]
    self.assertIn(
      "not wireguard_controller_existing_macos_wireguard_config.stat.exists",
      wait_task,
    )
    self.assertIn("wireguard_controller_rebootstrap_required", wait_task)

  def test_recreated_guests_are_rebootstrapped_only_after_lima_access_proves_unlocked(self) -> None:
    probe = "Test ordinary Lima access only to identify recreated unlocked guests"
    decide = "Decide whether existing controller state points to recreated unlocked guests"
    refuse = "Refuse controller recovery from legacy locked guests"
    self.assertLess(self.controller.index(probe), self.controller.index(decide))
    self.assertLess(self.controller.index(decide), self.controller.index(refuse))
    decision = self.controller[
      self.controller.index(decide):self.controller.index(refuse)
    ]
    self.assertIn("wireguard_controller_recreated_lima_paths.results", decision)
    self.assertIn("selectattr('rc', 'equalto', 0)", decision)
    clear = "Clear stale WireGuard host keys only for proven recreated local guests"
    clear_task = self.controller[
      self.controller.index(clear):self.controller.index(
        "Render the macOS WireGuard configuration from Vault"
      )
    ]
    self.assertIn("wireguard_controller_rebootstrap_required | bool", clear_task)
    self.assertIn("dest: \"{{ wireguard_known_hosts }}\"", clear_task)


if __name__ == "__main__":
  unittest.main()
