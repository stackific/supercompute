# Ansible playbooks and roles

Ansible is the only supported path for provider and infrastructure lifecycle. Task invokes playbooks via `scripts/ansible-playbook.sh`.

## Playbooks

| Playbook | Purpose |
| --- | --- |
| `playbooks/prod-wireguard-up.yml` | Classify static/roaming nodes; hub selection; controller + nodes |
| `playbooks/prod-wireguard-status.yml` | Mesh status |
| `playbooks/lima-up.yml` | Create/start `node_lima_guest` VMs |
| `playbooks/lima-status.yml` | Lima resource status |
| `playbooks/lima-destroy.yml` | Destroy Lima guests |
| `playbooks/cluster-up.yml` | `cluster_node` role with `cluster_lifecycle: present` |
| `playbooks/cluster-down.yml` | Surgical cluster undo |
| `playbooks/verify.yml` | Verification checks |
| `playbooks/wireguard-*.yml` | Legacy/local wireguard paths (not primary for `public` meshes) |

## Primary roles

| Role | Purpose |
| --- | --- |
| `prod_wireguard_controller` | macOS controller `scwg0`, LaunchDaemon |
| `prod_wireguard_node` | Ubuntu nodes: WireGuard, hub forwarding, syncconf |
| `lima` | Lima guest lifecycle |
| `cluster_node` | gVisor, Docker CE, PowerDNS GeoIP, geoipupdate |
| `wireguard_verify` | Post-up verification |

## `prod-wireguard-up` flow (summary)

1. **localhost** — Assert `provider.platform: public`; classify static vs roaming; pick `prod_wireguard_hub` (first static host).
2. **localhost** — `prod_wireguard_controller` role.
3. **localhost** — Probe mesh SSH; choose bootstrap vs mesh transport per node.
4. **wireguard_nodes** — `prod_wireguard_node` with bootstrap SSH (public, Cloudflare, or Lima-local).

## `cluster_node` role

Controlled by `cluster_lifecycle`:

- **`present`** — Install packages, configure PowerDNS listen addresses, GeoIP timer, Docker, gVisor.
- **`absent`** — Remove cluster software; leave WireGuard intact.

Defaults in `roles/cluster_node/defaults/main.yml` (zone apex, NS hostname, hub host).

## Inventory groups used

| Group | Playbook usage |
| --- | --- |
| `controller` | macOS localhost |
| `deployment` | Cluster software targets |
| `wireguard_nodes` | Mesh participants |

See [inventories.md](inventories.md) and [wireguard.md](wireguard.md).
