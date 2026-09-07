# Prerequisites

## Host environment

| Requirement | Used for |
| --- | --- |
| macOS Apple Silicon | Mac control plane (`task up`), Lima guests |
| [Task](https://taskfile.dev/installation/) | All `task …` entrypoints |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Locked Ansible venv (`uv sync --locked`) |
| WireGuard (`wg`, `wg-quick`) | Mesh bring-up and status |
| [Lima](https://lima-vm.io/docs/installation/) | `node_lima_guest` hosts under `dev` |

```sh
brew install go-task/tap/go-task uv wireguard-tools lima
task setup
```

`task setup` runs `uv lock --check`, `uv sync --locked`, verifies Ansible, and fetches the SHA-pinned rathole Linux amd64 binary into `.vendor/rathole/` (copied to Ubuntu nodes by Ansible).

GHA-managed inventories do **not** require a Mac for mutations — see [gha-deploy.md](gha-deploy.md).

## Deployment namespace (`hosts.yml`)

`inventories/<provider>/hosts.yml` → `all.vars` requires:

| Key | Purpose |
| --- | --- |
| `project` | Stable id (currently `example`) |
| `sc_ns` | Nameserver FQDN (default `ns.example.com`); parent zone seeds Mac LaunchDaemon reverse-DNS. Must have a parent zone (at least three labels). |
| `sc_api` | API FQDN (default `sc-api.example.com`) |
| `sc_app` | App FQDN (default `sc-app.example.com`) |
| `sc_apps` | Apps zone FQDN (default `sc-apps.example.com`) |

`project` prefixes:

- SSH key path: `~/.ssh/<project>-<provider>`
- Lima runtime home: `~/.lima/.<project>-<provider>`
- WireGuard LaunchDaemon label on macOS
- Vault ID label: `<project>-<provider>`

The same identity (`project`, `sc_ns`, `sc_api`, `sc_app`, `sc_apps`) is rendered to **`/etc/supercompute/hosts.yml`** on every deployment node during WireGuard reconcile. That copy adds a `hosts` list (`name`, `private_address`, `type`: `public` | `roaming` | `lima`, and `public_ip` for public hosts) from inventory. Container env vars are a subset of those FQDNs — see [cluster.md](cluster.md).

Changing `project` after go-live creates new paths and labels; it does not migrate existing state.

## Operator SSH identity

Create once per deployment (empty passphrase; store in password manager):

```sh
ssh-keygen -t ed25519 -a 100 \
  -f ~/.ssh/<project>-<provider> \
  -C "<project> <provider>"
ssh-add ~/.ssh/<project>-<provider>
```

Inventory references this key via `ssh_private_key_file` in `group_vars/all/main.yml`. For GHA, the same private key is repository secret `OPS_SSH_PRIVATE_KEY`.

## Node OS

- Ubuntu **26.04** (codename `resolute` in inventory defaults).
- Static / non-Lima: **`x86_64`** (`node_host_architecture: x86_64`).
- Lima guests: **`aarch64`** (`node_host_architecture: aarch64` — the value `arm` fails Ansible asserts).

## Inventory before first `up`

Each provider needs:

- `inventories/<provider>/hosts.yml`
- `inventories/<provider>/group_vars/all/main.yml` (include `control_plane: mac` or `gha`)
- `inventories/<provider>/group_vars/all/vault.yml` (after `task vault-init`)

`inventories/prod/` is committed in the repository (fill placeholders before `task up`). Only `inventories/<env>/.vault-pass` stays off-repo (gitignored).

## External services

Not installed by this repo but required for full stack operation:

- **Public IP** on each dialable static
- **Postgres database with owner role** hosted outside of the Supercompute cloud (not installed by this automation)
- Inbound **TCP 2333** on the rathole hub when non-Lima roaming exists
