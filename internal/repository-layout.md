# Repository layout

Worktree root paths (high level):

```text
Taskfile.yml            # includes taskfiles/*.yml
taskfiles/              # setup, vault, lima, wireguard, cluster
inventories/
  dev/                  # tracked dev mesh
  prod/                 # gitignored — operator backup
playbooks/              # Ansible playbooks
roles/                  # Ansible roles
scripts/                # Python + shell helpers invoked by Task / GHA
.github/workflows/      # manual deploy.yml (control_plane=gha)
internal/               # this documentation
docs/                   # Starlight public docs site (Bun + Astro)
.state/<provider>/      # runtime state (known_hosts, wireguard, lima, gha-*)
```

## `inventories/<provider>/hosts.yml`

Operator source of truth per environment. Required shape:

```yaml
all:
  vars:
    project: example
    hostname: example.com

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
| `hostname` | Cloud DNS suffix (for example `example.com`); Supercompute prepends `dns_prefix_*` from `group_vars/all/main.yml`. If the DNS is hosted on Cloudflare, do not enable the proxy orange icons. |

During WireGuard reconcile, `supercompute_config` renders identity plus a mesh `hosts` list to **`/etc/supercompute/hosts.yml`** on every deployment node, with sidecars `public-endpoints.list` and (on roaming) `roaming-transit.ips`.

## `inventories/<provider>/` (other files)

| Path | Purpose |
| --- | --- |
| `group_vars/all/main.yml` | Platform, `control_plane`, mesh CIDR, Lima/SSH defaults, DNS prefixes |
| `group_vars/all/vault.yml` | Encrypted secrets (`ansible-vault`; committed) |
| `.vault-pass` | Vault password (gitignored; local or GHA secret) |

Additional `group_vars/<group>/` files may exist (for example `nodes`).

## `.state/<provider>/`

Created by automation; not committed.

| Path | Purpose |
| --- | --- |
| `known_hosts` | SSH host-key aliases for mesh and bootstrap |
| `wireguard/` | Generated Mac `scwg0.conf` and keys synced from vault |
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

## `docs/`

Starlight documentation **website** (landing page, guides). Operator runbooks are in `internal/`, not under `docs/src/content/docs/` unless copied there deliberately.

## Ansible execution

`scripts/ansible-playbook.sh` selects inventory `inventories/<ENV>/`, vault password from `.vault-pass`, and runs playbooks with the locked venv:

```sh
uv run --locked ansible-playbook …
```

Identity vars (`project`, `hostname`) load from `hosts.yml` → `all.vars`. Nameserver, API, app, and apps names are derived from `hostname`.

## Related

- [inventories.md](inventories.md) — host variables and groups
- [ansible.md](ansible.md) — playbooks and roles
- [gha-deploy.md](gha-deploy.md) — Actions workflow layout
