# Inventories

Each **provider** is an Ansible inventory directory: `inventories/<slug>/`. The slug is passed as `PROVIDER` to Task (`PROVIDER=dev`, `PROVIDER=prod`).

## Required files

| File | Role |
| --- | --- |
| `hosts.yml` | Hosts and group membership |
| `group_vars/all/main.yml` | Provider platform, mesh, Lima, SSH defaults |
| `group_vars/all/vault.yml` | Encrypted secrets (after `task vault-init`) |

## Host groups

Typical structure in `hosts.yml`:

| Group | Hosts | Role |
| --- | --- | --- |
| `controller` | `localhost` | macOS Ansible controller |
| `deployment` | `static-1`, `roaming-1`, … | Nodes that receive cluster software |
| `wireguard_nodes` | `deployment` (children) | WireGuard mesh participants |

## `provider` mapping (`main.yml`)

```yaml
provider:
  slug: "{{ inventory_dir | ansible.builtin.basename }}"
  mode: remote
  platform: public
```

- **`platform: public`** — required. Dispatches `wg-*` to production WireGuard playbooks.
- **`platform: vps`** — refused (rename to `public`).
- **`platform: lima`** — refused (use `node_lima_guest` under `public`).

`provider.mode: remote` is required for `prod-wireguard-up`.

## Per-host variables (`hosts.yml`)

| Variable | Static public | Roaming (non-Lima) | Lima guest |
| --- | --- | --- | --- |
| `prod_wireguard_address` | Mesh IP | Mesh IP | Mesh IP |
| `prod_wireguard_endpoint` | Public IPv4 | — | — |
| `prod_ssh_host_ed25519_sha256` | Manual | Manual | Auto via `lima-up` |
| `wireguard_roaming` | — | `true` | `true` |
| `node_lima_guest` | — | — | `true` |
| `node_host_architecture` | `x86_64` | `x86_64` | `aarch64` |
| `prod_bootstrap_ssh_host` | — | Cloudflare hostname | — |

Lima guests **must not** set `prod_bootstrap_ssh_host` or `prod_wireguard_endpoint`.

## Mesh CIDR

Set in `group_vars/all/main.yml`:

| Inventory | Typical CIDR |
| --- | --- |
| `dev` | `10.217.80.0/24` |
| `prod` | `10.217.79.0/24` (operator choice) |

Controller address is usually `.1` (`prod_wireguard_controller_address`).

## Lima node list

`lima_nodes` in `main.yml` maps inventory host names to Lima ports and mesh addresses:

```yaml
lima_nodes:
  - name: roaming-1
    wg_address: 10.217.80.21
    ssh_port: 61221
    wg_host_port: 51981
    mac_address: "52:55:55:80:00:21"
```

Only hosts with `node_lima_guest: true` are managed by `lima-*` tasks.

## Tracked vs operator-local

| Inventory | In git |
| --- | --- |
| `inventories/dev/` | Yes (placeholders for endpoints/fingerprints) |
| `inventories/prod/` | No — gitignored; restore from backup |

## Related

- [setup-dev.md](setup-dev.md) — `dev` inventory walkthrough
- [setup-prod.md](setup-prod.md) — production inventory
- [wireguard.md](wireguard.md) — roaming and hub semantics
