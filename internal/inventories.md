# Inventories

Each **provider** is an Ansible inventory directory: `inventories/<slug>/`. The slug is passed as `ENV` to Task (`ENV=dev`, `ENV=prod`).

## Required files

| File | Role |
| --- | --- |
| `hosts.yml` | Project identity (`all.vars`) and host definitions |
| `group_vars/all/main.yml` | Provider platform, mesh, Lima, SSH defaults, DNS prefixes |
| `group_vars/all/vault.yml` | Encrypted secrets (after `task vault-init`) |
| `group_vars/nodes/main.yml` | SSH connection defaults for remote nodes (mesh `ansible_host`, keys, known_hosts) |

## Host groups

Typical structure in `hosts.yml`:

```yaml
all:
  vars:
    project: example
    hostname: sc.example.com

nodes:
  hosts:
    static-1:
      public_ip: "…"
      private_address: 10.217.80.11
      …
```

Playbooks that run on the operator machine use `hosts: localhost` (Mac or GitHub runner). That host is **not** listed in `hosts.yml`.

## `all.vars` deployment settings

Required in every inventory before `task up` (`scripts/validate-deployment.py`):

| Variable | Example | Notes |
| --- | --- | --- |
| `project` | `example` | Stable id |
| `hostname` | `sc.example.com` | Cloud DNS suffix. Supercompute prepends `dns_prefix_*` from `group_vars/all/main.yml`. If the DNS is hosted on Cloudflare, do not enable the proxy orange icons. |

| Vault key | Example | Notes |
| --- | --- | --- |
| `vault_database_url` | `postgresql://user:pass@host:5432/db` | Placeholder at `vault-init` (`postgresql://REPLACE_WITH_USER:PASSWORD@HOST:5432/DATABASE`); replace via `task vault-edit` |
| `vault_database_secret` | auto-generated | Created by `task vault-init`; copied to nodes as `database_secret` |

`task up` requires both vault keys above. `ensure-secrets` recreates the database secret only when missing.

## Node config file (`/etc/supercompute/hosts.yml`)

`supercompute_config` installs this on every `nodes` host during `task up`. It is rendered from inventory `all.vars` plus the mesh host list:

| Field | Source |
| --- | --- |
| `project`, `hostname` | `hosts.yml` `all.vars` |
| `nameserver_hostname`, `sc_api`, `sc_app`, `sc_apps` | Derived: `dns_prefix_*` from `group_vars/all/main.yml` + `hostname` |
| `database_url` on the node | `vault_database_url` from the encrypted vault |
| `database_secret` on the node | `vault_database_secret` from the encrypted vault |
| `hosts` | `nodes` group (name, `private_address`, type, `public_ip` for statics) |

Edit `inventories/<slug>/hosts.yml` and re-run `task up` to push changes.

## `provider` mapping (`main.yml`)

```yaml
provider:
  slug: "{{ inventory_dir | ansible.builtin.basename }}"
  mode: remote
  platform: public
```

- **`platform: public`** — required. Dispatches `wg-*` / `up` to production WireGuard playbooks.
- **`platform: vps`** — refused (rename to `public`).
- **`platform: lima`** — refused (use `node_lima_guest` under `public`).

`provider.mode: remote` is required for `wireguard-up`.

## Control plane and mesh vars (`main.yml`)

| Variable | Typical | Purpose |
| --- | --- | --- |
| `control_plane` | `mac` or `gha` | Who mutates the mesh; default `mac` |
| `node_include_controller_peer` | derived | Include Mac `.1` peer when not `gha` |
| `node_controller_address` | `.1` in CIDR | Mac mesh IP (`control_plane: mac`) |
| `node_ci_address` | e.g. `.254` | Ephemeral GHA runner mesh IP (unique in CIDR) |
| `node_forward_on_all_statics` | `true` | Every public static forwards for day-2 random dial |
| `roaming_dial_timer_on_calendar` | `hourly` | systemd timer for roaming dial helper |
| `mac_operator_ssh_public_key` | from env | Optional; GHA installs into `ops` authorized_keys |

When `control_plane: gha`, see [gha-deploy.md](gha-deploy.md).

## Per-host variables (`hosts.yml`)

| Variable | Static public | Roaming (non-Lima) | Lima guest |
| --- | --- | --- | --- |
| `private_address` | Mesh IP | Mesh IP | Mesh IP |
| `public_ip` | Public IPv4 | — | — |
| `ssh_ed25519_sha256` | Manual | Manual | Auto via `lima-up` |
| `roaming` | — | `true` | `true` |
| `node_lima_guest` | — | — | `true` |
| `node_host_architecture` | `x86_64` | `x86_64` | `aarch64` |
| `bootstrap_ssh_host` | — | Cloudflare hostname | — |

Lima guests **must not** set `bootstrap_ssh_host` or `public_ip`.

## Mesh CIDR

Set in `group_vars/all/main.yml`:

| Inventory | Typical CIDR |
| --- | --- |
| `dev` | `10.217.80.0/24` (static hub only) |
| `dev-lima` | `10.217.81.0/24` (static + Lima roaming) |
| `prod` | `10.217.79.0/24` (two static hubs) |

Controller address is usually `.1` (`node_controller_address`) for the Mac peer. GHA inventories also set `node_ci_address` (often `.254`) for the ephemeral runner peer — not a permanent node.

## Lima node list

`lima_nodes` in `main.yml` maps inventory host names to Lima ports and mesh addresses:

```yaml
lima_nodes:
  - name: roaming-1
    address: 10.217.81.21
    ssh_port: 61222
    host_port: 51982
    mac_address: "52:55:55:81:00:21"
```

Only inventories with `node_lima_guest` hosts (e.g. **`dev-lima`**) define `lima_nodes`. **`dev`** has no Lima block.

Only hosts with `node_lima_guest: true` are managed by `lima-*` tasks (`ENV=<slug>`).

## Tracked vs operator-local

| Inventory | In git |
| --- | --- |
| `inventories/dev/` | Yes (static hub only) |
| `inventories/dev-lima/` | Yes (static + Lima roaming) |
| `inventories/prod/` | Yes (two static hubs; fill placeholders before `task up`) |

Vault password files (`inventories/*/.vault-pass`) are always gitignored.

## Related

- [setup-dev.md](setup-dev.md) — `dev` inventory walkthrough
- [setup-prod.md](setup-prod.md) — production inventory
- [gha-deploy.md](gha-deploy.md) — `control_plane: gha`
- [wireguard.md](wireguard.md) — roaming and hub semantics
