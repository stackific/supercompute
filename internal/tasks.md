# Task reference

All tasks run from the **worktree root**. Most require `PROVIDER=<inventory_slug>`.

List everything:

```sh
task --list
```

## Project (`taskfiles/project.yml`)

| Task | Description |
| --- | --- |
| `task setup` | Install locked Ansible venv; macOS installs `cloudflared` if missing |

## Vault (`taskfiles/vault.yml`)

| Task | Description |
| --- | --- |
| `task vault-init PROVIDER=<slug>` | New encrypted vault + password file |
| `task vault-edit PROVIDER=<slug>` | Edit vault in `$EDITOR` |
| `task vault-wireguard-ensure PROVIDER=<slug>` | Ensure WG keys in vault |
| `task vault-reset PROVIDER=<slug> CONFIRM=reset-vault-<slug>` | Empty vault + new password |
| `task vault-destroy PROVIDER=<slug> CONFIRM=destroy-vault-<slug>` | Delete vault files |

## Lima (`taskfiles/lima.yml`)

Only affects hosts with `node_lima_guest: true`.

| Task | Description |
| --- | --- |
| `task lima-up PROVIDER=<slug>` | Create/start guests; auto-fill fingerprints |
| `task lima-host-fingerprints PROVIDER=<slug>` | Capture ED25519 fingerprints into `hosts.yml` |
| `task lima-status PROVIDER=<slug>` | Resource table without creating state |
| `task lima-destroy PROVIDER=<slug> CONFIRM=destroy-lima-<slug>` | Destroy guests and disks |

## Lifecycle (`taskfiles/cluster.yml`)

Requires `provider.platform: public`. Refuses `vps` and `lima`.

| Task | Description |
| --- | --- |
| `task up PROVIDER=<slug>` | WireGuard mesh + gVisor/Docker/PowerDNS on `deployment` hosts |
| `task down PROVIDER=<slug> CONFIRM=down-<slug>` | Undo cluster stack, node WireGuard, and Mac controller mesh |

## WireGuard helpers (`taskfiles/wireguard.yml`)

| Task | Description |
| --- | --- |
| `task wg-status PROVIDER=<slug>` | Mesh status |
| `task wg-remove PROVIDER=<slug>` | Disconnect Mac controller only (nodes unchanged) |
| `task ssh PROVIDER=<slug> NODE=<host>` | SSH over mesh |

## Typical sequences

**Dev mesh:**

```sh
task setup
task lima-up PROVIDER=dev
task vault-init PROVIDER=dev
task up PROVIDER=dev
```

**Prod mesh** (after restoring `inventories/prod/`):

```sh
task vault-init PROVIDER=prod   # or restore vault from backup
task up PROVIDER=prod
```

See [get-started.md](get-started.md) and runbooks in this directory.
