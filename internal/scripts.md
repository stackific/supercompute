# Scripts reference

Python helpers use **`uv run --locked`** from the worktree root. Shell scripts are invoked by Task.

## Ansible wrapper

| Script | Role |
| --- | --- |
| `scripts/ansible-playbook.sh` | Runs `ansible-playbook` with inventory, vault password, locked venv |
| `scripts/config_project.py` | Prints `project` from `inventories/<provider>/hosts.yml` all.vars (`--provider` or `ENV`) |

## Provider / inventory

| Script | Role |
| --- | --- |
| `scripts/provider_platform.py` | Prints `provider.platform`; refuses `vps` / `lima` |

## WireGuard / SSH

| Script | Role |
| --- | --- |
| `scripts/known-hosts.py` | Sync `.state/<provider>/known_hosts` from `hosts.yml` fingerprints |
| `scripts/wireguard-ssh-config.py` | Generate SSH config snippets for mesh/bootstrap |
| `scripts/wg-ssh.sh` | `task ssh` entrypoint |
| `scripts/disconnect-wireguard.sh` | `task wg-remove` for public meshes |
| `scripts/gha-mesh-peer.sh` | Ephemeral GHA runner WireGuard peer (`control_plane=gha`) |
| `scripts/dev_reset_controller_wireguard.py` | Dev-reset controller teardown when `.state/dev` is absent |
| `scripts/wireguard_ssh_target.py` | Resolve SSH target for a node |
| `scripts/select-wireguard-interface.py` | Pick WireGuard interface name |

## Lima

| Script | Role |
| --- | --- |
| `scripts/lima-runtime-home.sh` | Resolve `LIMA_HOME` for a provider |
| `scripts/lima_release_host_ports.py` | Terminate orphan `limactl` UDP forwards for inventory ports |
| `scripts/lima_nodes.py` | Map inventory hosts to Lima node definitions |
| `scripts/lima_instances.py` | Lima instance metadata |
| `scripts/lima-host-fingerprints.py` | Scan guests; write `ssh_ed25519_sha256` to `hosts.yml` (`--force` after recreate) |

## Vault

| Script | Role |
| --- | --- |
| `scripts/vault.py` | `vault-init`, `edit`, `destroy`, `ensure-wireguard` |

## Common invocations

```sh
uv run --locked python scripts/provider_platform.py --provider dev
uv run --locked python scripts/lima-host-fingerprints.py --provider dev --force
uv run --locked python scripts/vault.py ensure-wireguard
```

See [tasks.md](tasks.md) for Task entrypoints that call these scripts.
