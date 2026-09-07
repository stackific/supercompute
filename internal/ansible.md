# Ansible playbooks and roles

Ansible is the only supported path for provider and infrastructure lifecycle. Task invokes playbooks via `scripts/ansible-playbook.sh`. GHA invokes the same wrapper with `--extra-vars @.state/<provider>/gha-extra-vars.yml`.

## Playbooks

| Playbook | Purpose |
| --- | --- |
| `playbooks/wireguard-up.yml` | Classify static/roaming; hub; Mac controller when `control_plane!=gha`; nodes |
| `playbooks/wireguard-down.yml` | Tear down node WireGuard (`wireguard_node` absent) |
| `playbooks/wireguard-status.yml` | Mesh status |
| `playbooks/gha-mesh-peer.yml` | Ephemeral GitHub Actions WireGuard peer on nodes |
| `playbooks/lima-up.yml` | Create/start `node_lima_guest` VMs |
| `playbooks/lima-status.yml` | Lima resource status |
| `playbooks/lima-destroy.yml` | Destroy Lima guests |
| `playbooks/cluster-up.yml` | `cluster_node` role with `cluster_lifecycle: present` |
| `playbooks/cluster-down.yml` | Surgical cluster undo |
| `playbooks/verify.yml` | Verification checks |
| `playbooks/node-transport.yml` | Shared mesh vs bootstrap SSH selection for down playbooks |
| `playbooks/env-reset-controller.yml` | Mac controller cleanup during `env-reset` |

## Primary roles

| Role | Purpose |
| --- | --- |
| `wireguard_controller` | macOS controller `scwg0`, LaunchDaemon (`control_plane: mac`) |
| `wireguard_node` | Ubuntu nodes: WireGuard, static forwarding, roaming dial helper, syncconf |
| `supercompute_config` | Ubuntu nodes: `/etc/supercompute/hosts.yml` + dial sidecars |
| `lima` | Lima guest lifecycle (`dev-lima` testing) |
| `cluster_node` | gVisor, Docker CE, Caddy, PowerDNS |

## `wireguard-up` flow (summary)

1. **localhost** — Assert `provider.platform: public`; classify static vs roaming; pick `static_hub` (first static host).
2. **localhost** — `wireguard_controller` when `control_plane` is not `gha`.
3. **localhost** — Probe mesh SSH (3s static / 15s roaming or Lima); choose bootstrap vs mesh transport per node.
4. **nodes** — `wireguard_node` with bootstrap SSH (public, Cloudflare, or Lima-local); install `/etc/supercompute/*`; post-up roaming dial helper + timer.

## `cluster_node` role

Controlled by `cluster_lifecycle`:

- **`present`** — Install gVisor, Docker, PowerDNS, and Caddy; pull and run the `sc` and `supercompute` containers (`unless-stopped`; recreate from `:latest` when already present); set `SC_API` on `sc` and `SC_DASH` on `supercompute`; point `sc-app.` at `sc` and `sc-api.` at `supercompute`.
- **`absent`** — Remove cluster software; leave WireGuard intact.

The nameserver hostname is `dns_prefix_ns` from `group_vars/all/main.yml` plus `hostname` from `inventories/<provider>/hosts.yml` → `all.vars`. If the DNS is hosted on Cloudflare, do not enable the proxy orange icons.

## Inventory groups used

| Group | Playbook usage |
| --- | --- |
| `localhost` | Controller-side roles, verify (Mac or GHA runner) |
| `nodes` | Mesh and cluster roles |

See [inventories.md](inventories.md), [wireguard.md](wireguard.md), and [gha-deploy.md](gha-deploy.md).
