# Repository layout

Worktree root paths (high level):

```text
Taskfile.yml            # includes taskfiles/*.yml
taskfiles/              # setup, vault, lima, wireguard, cluster
inventories/
  dev/                  # tracked dev mesh
  prod/                 # gitignored — operator backup
playbooks/              # Ansible playbooks
roles/                  # Ansible roles (including rathole)
scripts/                # Python + shell helpers invoked by Task / GHA
.github/workflows/      # manual deploy.yml (control_plane=gha)
internal/               # this documentation
docs/                   # Starlight public docs site (Bun + Astro)
.vendor/rathole/        # SHA-pinned rathole binary from task setup (gitignored)
.state/<provider>/      # runtime state (known_hosts, wireguard, rathole, lima, gha-*)
```

## `inventories/<provider>/hosts.yml`

Operator source of truth per environment. Required shape:

```yaml
all:
  vars:
    project: example
    sc_ns: ns.example.com
    sc_api: sc-api.example.com
    sc_app: sc-app.example.com
    sc_apps: sc-apps.example.com

nodes:
  hosts:
    static-1:
      public_ip: "…"
      private_address: 10.217.80.11
      …
```

| Key (under `all.vars`) | Purpose |
| --- | --- |
| `project` | Stable id; vault label, SSH key path, Lima home, LaunchDaemon |
| `sc_ns`, `sc_api`, `sc_app`, `sc_apps` | Nameserver, API, app, and apps FQDNs copied to `/etc/supercompute/hosts.yml`. `sc_ns` parent zone seeds Mac LaunchDaemon reverse-DNS. |

During WireGuard reconcile, `supercompute_config` renders identity plus a mesh `hosts` list to **`/etc/supercompute/hosts.yml`** on every deployment node, with sidecars `public-endpoints.list` and (on roaming) `roaming-transit.ips`.

## `inventories/<provider>/` (other files)

| Path | Purpose |
| --- | --- |
| `group_vars/all/main.yml` | Platform, `control_plane`, mesh CIDR, Lima/SSH defaults |
| `group_vars/all/vault.yml` | Encrypted secrets (`ansible-vault`; committed) |
| `.vault-pass` | Vault password (gitignored; local or GHA secret) |

Additional `group_vars/<group>/` files may exist (for example `nodes`).

## `.state/<provider>/`

Created by automation; not committed.

| Path | Purpose |
| --- | --- |
| `known_hosts` | SSH host-key aliases for mesh and bootstrap |
| `wireguard/` | Generated Mac `scwg0.conf` and keys synced from vault |
| `rathole/` | Generated roaming client install scripts |
| `lima/` | Lima instance definitions for `node_lima_guest` hosts |
| `gha-extra-vars.yml` | GHA workflow Ansible extras (`control_plane: gha`, optional Mac pubkey) |
| `gha-peer/` | Ephemeral CI WireGuard keys/conf on the **GitHub runner** only |

Lima **runtime** VMs live under `~/.lima/.<project>-<provider>/` (see [lima.md](lima.md)).

## On-node paths

| Path | Purpose |
| --- | --- |
| `/etc/supercompute/hosts.yml` | Project + mesh host list |
| `/etc/supercompute/public-endpoints.list` | Public static dial targets (root `0600`) |
| `/etc/supercompute/roaming-transit.ips` | Transit AllowedIPs for roaming dial helper |
| `/usr/local/sbin/supercompute-roaming-dial` | Post-build random static dial (`shuf` + `wg set`) |
| `/etc/wireguard/<iface>.conf` | Node WireGuard interface config |
| `/usr/local/bin/rathole` | SHA-pinned rathole on hub and non-Lima roaming |
| `/etc/rathole/*.toml` | Rathole server/client config (mode `0600`) |

## `docs/`

Starlight documentation **website** (landing page, guides). Operator runbooks are in `internal/`, not under `docs/src/content/docs/` unless copied there deliberately.

## Ansible execution

`scripts/ansible-playbook.sh` selects inventory `inventories/<ENV>/`, vault password from `.vault-pass`, and runs playbooks with the locked venv:

```sh
uv run --locked ansible-playbook …
```

Identity vars (`project`, `sc_ns`, `sc_api`, `sc_app`, `sc_apps`) load from `hosts.yml` → `all.vars`.

## Related

- [inventories.md](inventories.md) — host variables and groups
- [ansible.md](ansible.md) — playbooks and roles
- [gha-deploy.md](gha-deploy.md) — Actions workflow layout
