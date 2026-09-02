# Task reference

All tasks run from the **worktree root**. Environment-scoped tasks require `ENV=<inventory_slug>`.

List public tasks:

```sh
task --list
```

## Public surface

### Project (`taskfiles/project.yml`)

| Task | Description |
| --- | --- |
| `task setup` | Install locked Ansible venv |

### Vault (`taskfiles/vault.yml`)

| Task | Description |
| --- | --- |
| `task vault-init ENV=<env>` | New encrypted vault + password file |
| `task vault-edit ENV=<env>` | Open vault, edit secrets, save and exit |

### Lima (`taskfiles/lima.yml`)

Requires `ENV=<slug>` with `node_lima_guest` hosts (typically **`dev-lima`**).

| Task | Description |
| --- | --- |
| `task lima-up ENV=<env>` | Create/start guests; auto-fill fingerprints |
| `task lima-status ENV=<env>` | Resource table without creating state |

### Lifecycle (`taskfiles/cluster.yml`)

| Task | Description |
| --- | --- |
| `task up ENV=<env>` | Validate deployment config, ensure vault secrets, WireGuard mesh + cluster stack |
| `task down ENV=<env> CONFIRM=down-<slug>` | Stop cluster + WireGuard; **keeps** vault, `.state/`, Lima |
| `task env-reset ENV=<env> CONFIRM=reset-<slug>` | Factory reset: down (retried), vault delete, `.state/` delete, optional Lima destroy |
| `task dev-reset CONFIRM=reset-dev` | Alias for `env-reset ENV=dev` (no Lima) |
| `task dev-reset-lima CONFIRM=reset-dev-lima` | Alias for `env-reset ENV=dev-lima` |

### WireGuard helpers (`taskfiles/wireguard.yml`)

| Task | Description |
| --- | --- |
| `task wg-status ENV=<env>` | Mesh status |
| `task wg-remove ENV=<env>` | Disconnect Mac controller only (nodes unchanged) |
| `task ssh ENV=<env> NODE=<host>` | SSH over mesh |

## `down` vs reset

| | `down` | `env-reset` / `dev-reset` / `dev-reset-lima` |
| --- | --- | --- |
| Vault + `.vault-pass` | Kept | Deleted |
| `.state/<slug>/` | Kept | Deleted |
| Lima guests | Kept | Destroyed (when inventory has them) |
| Bring back | `task up` | `vault-init` (+ `lima-up` for dev-lima), then `up` |

## Internal tasks (`internal: true`)

Hidden from `task --list`; still callable for troubleshooting:

| Task | Description |
| --- | --- |
| `vault-secrets-ensure` | WG keys + `vault_database_secret` (`up` calls this) |
| `vault-wireguard-ensure` | WG keys only |
| `vault-destroy` | Vault delete without full reset |
| `lima-host-fingerprints` | Fingerprint capture (`lima-up` runs `--force`) |
| `lima-destroy` | Lima delete without full reset |
| `wg-syntax` | Playbook syntax check |
| `lock-verify` | `uv.lock` pin verification (`setup` calls this) |

## Typical sequences

**Dev (static only):**

```sh
task setup
task vault-init ENV=dev
task vault-edit ENV=dev
task up ENV=dev
```

**dev-lima:**

```sh
task setup
task lima-up ENV=dev-lima
task vault-init ENV=dev-lima
task vault-edit ENV=dev-lima
task up ENV=dev-lima
```

See [get-started.md](get-started.md) and public [Get started locally with a roaming node](../docs/src/content/docs/start-here/get-started-roaming-node.mdx).
