# Prerequisites

## Host environment

| Requirement | Used for |
| --- | --- |
| macOS Apple Silicon | Controller, Lima guests |
| [Task](https://taskfile.dev/installation/) | All `task …` entrypoints |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Locked Ansible venv (`uv sync --locked`) |
| WireGuard (`wg`, `wg-quick`) | Mesh bring-up and status |
| [Lima](https://lima-vm.io/docs/installation/) | `node_lima_guest` hosts under `dev` |
| `cloudflared` (macOS via `task setup`) | Non-Lima roaming SSH bootstrap only |

```sh
brew install go-task/tap/go-task uv wireguard-tools lima
task setup
```

`task setup` runs `uv lock --check`, `uv sync --locked`, verifies Ansible, and on macOS installs `cloudflared` via Homebrew when missing.

## Deployment namespace

`cloud.yml` at the worktree root defines `cloud_name` (currently `sc`). This name prefixes:

- SSH key path: `~/.ssh/<cloud_name>-<provider>`
- Lima runtime home: `~/.lima/.<cloud_name>-<provider>`
- WireGuard LaunchDaemon label on macOS
- Vault ID label: `<cloud_name>-<provider>`

Changing `cloud_name` after go-live creates new paths and labels; it does not migrate existing state.

## Operator SSH identity

Create once per deployment (empty passphrase; store in password manager):

```sh
ssh-keygen -t ed25519 -a 100 \
  -f ~/.ssh/<cloud_name>-<provider> \
  -C "<cloud_name> <provider>"
ssh-add ~/.ssh/<cloud_name>-<provider>
```

Inventory references this key via `cloud_ssh_private_key_file` in `group_vars/all/main.yml`.

## Node OS

- Ubuntu **26.04** (codename `resolute` in inventory defaults).
- Static / non-Lima: **`x86_64`** (`node_host_architecture: x86_64`).
- Lima guests: **`aarch64`** (`node_host_architecture: aarch64` — the value `arm` fails Ansible asserts).

## Inventory before first `up`

Each provider needs:

- `inventories/<provider>/hosts.yml`
- `inventories/<provider>/group_vars/all/main.yml`
- `inventories/<provider>/group_vars/all/vault.yml` (after `task vault-init`)

`inventories/prod/` is **gitignored**; restore from operator backup.

## External services

Not installed by this repo but required for full stack operation:

- **Public IP** on the static hub
- **External Postgres** for application workloads
- **Cloudflare** zone and tunnel for non-Lima roaming
