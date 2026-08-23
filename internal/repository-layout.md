# Repository layout

Worktree root paths (high level):

```text
cloud.yml          # cloud_name namespace
Taskfile.yml            # includes taskfiles/*.yml
taskfiles/              # setup, vault, lima, wireguard, cluster
inventories/
  dev/                  # tracked dev mesh
  prod/                 # gitignored — operator backup
playbooks/              # Ansible playbooks
roles/                  # Ansible roles
scripts/                # Python + shell helpers invoked by Task
internal/               # this documentation
docs/                   # Starlight public docs site (Bun + Astro)
.state/<provider>/      # runtime state (known_hosts, wireguard, lima)
```

## `inventories/<provider>/`

| Path | Purpose |
| --- | --- |
| `hosts.yml` | Host definitions, mesh addresses, endpoints, flags |
| `group_vars/all/main.yml` | Provider platform, mesh CIDR, Lima/Docker image defaults |
| `group_vars/all/vault.yml` | Encrypted secrets (`ansible-vault`) |
| `.vault-pass` | Local vault password file (gitignored pattern; operator-local) |

Additional `group_vars/<group>/` files may exist (for example `wireguard_nodes`).

## `.state/<provider>/`

Created by automation; not committed.

| Path | Purpose |
| --- | --- |
| `known_hosts` | SSH host-key aliases for mesh and bootstrap |
| `wireguard/` | Generated `scwg0.conf` and keys synced from vault |
| `lima/` | Lima instance definitions for `node_lima_guest` hosts |

Lima **runtime** VMs live under `~/.lima/.<cloud_name>-<provider>/` (see [lima.md](lima.md)).

## `docs/`

Starlight documentation **website** (landing page, guides). Operator runbooks are in `internal/`, not under `docs/src/content/docs/` unless copied there deliberately.

## Ansible execution

`scripts/ansible-playbook.sh` selects inventory `inventories/<PROVIDER>/`, loads vault password from `.vault-pass`, and runs playbooks with the locked venv:

```sh
uv run --locked ansible-playbook …
```

## Related

- [inventories.md](inventories.md) — host variables and groups
- [ansible.md](ansible.md) — playbooks and roles
