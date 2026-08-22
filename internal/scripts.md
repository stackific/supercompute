# Scripts reference

Python helpers use **`uv run --locked`** from the worktree root. Shell scripts are invoked by Task.

## Ansible wrapper

| Script | Role |
| --- | --- |
| `scripts/ansible-playbook.sh` | Runs `ansible-playbook` with inventory, vault password, locked venv |

## Provider / inventory

| Script | Role |
| --- | --- |
| `scripts/provider_platform.py` | Prints `provider.platform`; refuses `vps` / `lima` |
| `scripts/deployment_name.py` | Prints `deployment_name` from `deployment.yml` |

## WireGuard / SSH

| Script | Role |
| --- | --- |
| `scripts/prod-known-hosts.py` | Sync `.state/<provider>/known_hosts` from `hosts.yml` fingerprints |
| `scripts/prod-wireguard-ssh-config.py` | Generate SSH config snippets for mesh/bootstrap |
| `scripts/wg-ssh.sh` | `task ssh` entrypoint |
| `scripts/disconnect-prod-wireguard.sh` | `task wg-remove` for public meshes |
| `scripts/wireguard_ssh_target.py` | Resolve SSH target for a node |
| `scripts/select-wireguard-interface.py` | Pick WireGuard interface name |

## Lima

| Script | Role |
| --- | --- |
| `scripts/lima-runtime-home.sh` | Resolve `LIMA_HOME` for a provider |
| `scripts/lima_nodes.py` | Map inventory hosts to Lima node definitions |
| `scripts/lima_instances.py` | Lima instance metadata |
| `scripts/lima-host-fingerprints.py` | Scan guests; write `prod_ssh_host_ed25519_sha256` to `hosts.yml` (`--force` after recreate) |

## Vault

| Script | Role |
| --- | --- |
| `scripts/vault.py` | `vault-init`, `edit`, `reset`, `destroy`, `ensure-wireguard` |

## Common invocations

```sh
uv run --locked python scripts/provider_platform.py --provider dev
uv run --locked python scripts/lima-host-fingerprints.py --provider dev --force
uv run --locked python scripts/vault.py ensure-wireguard
```

See [tasks.md](tasks.md) for Task entrypoints that call these scripts.
