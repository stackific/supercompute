# WireGuard mesh

Production meshes use interface **`scwg0`**, UDP port **`51830`** (inventory: `node_listen_port`), and addresses in the inventory mesh CIDR.

## Control planes

| `control_plane` | Who runs Ansible | Mac WG peer (`.1`) |
| --- | --- | --- |
| `mac` (default) | Mac `task up` | Required (`node_include_controller_peer`) |
| `gha` | GitHub Actions `deploy.yml` | Omitted; ephemeral runner uses `node_ci_address` |

See [gha-deploy.md](gha-deploy.md) for the GHA path. Do not Mac-`up` a GHA-managed inventory.

## Participants

| Party | Role |
| --- | --- |
| macOS controller | WireGuard peer at `node_controller_address` (usually `.1`) when `control_plane: mac` |
| GHA runner (ephemeral) | Temporary peer at `node_ci_address` (often `.254`) during Actions jobs only |
| Static public hosts | Stable `public_ip`; build-up hub = first static; day-2 dial targets |
| Roaming hosts | `roaming: true`; dial a public static; no inbound UDP 51830 at home |

Inventory hostnames: `static-1`, `static-2`, … and `roaming-1`, `roaming-2`, … (not `home-*` or `prod-*` prefixes).

## Roaming rules

1. **Roaming nodes always initiate** WireGuard toward a public static `Endpoint`.
2. Stable peers (Mac, static hosts) **do not dial** roaming nodes for mesh traffic.
3. **No DynDNS** or public hostname as WireGuard `Endpoint` for roaming peers.
4. **No inbound UDP 51830** port-forward on home routers for roaming nodes.

Cloudflare Tunnel carries **SSH bootstrap only**; it does not carry `scwg0` UDP.

## Build-up hub vs post-build dial

When any roaming node exists, `wireguard-up` selects the first static host as **`static_hub`** (typically `static-1`) for a **deterministic join**:

- Rendered roaming conf pins `Endpoint` + keepalive on that hub peer first.
- Hub (and, when `node_forward_on_all_statics: true`, **every public static**) enables `net.ipv4.ip_forward` and iptables `FORWARD` on the WG interface.
- After WireGuard starts, the role runs `wg-quick strip` + `wg syncconf` so `AllowedIPs` update without a full interface restart.

**After WG is up** (Mac and GHA paths), every roaming node runs `/usr/local/sbin/supercompute-roaming-dial`:

- Reads `/etc/supercompute/public-endpoints.list`
- Picks **one** public static with `shuf -n 1`
- `wg set` makes that peer the active Endpoint/transit (other statics keep mesh `/32` only)
- A systemd timer (`roaming_dial_timer_on_calendar`, default **`hourly`**) re-runs so the choice is not permanently fixed

Spoke-to-spoke roaming and Mac↔roaming traffic remain **relayed** through whichever static currently holds transit AllowedIPs; roaming peers do not peer directly with each other.

Mac controller conf (when present) still places roaming `/32`s on the **first hub** peer for Mac↔roaming.

## Mesh SSH probe

Before choosing bootstrap vs mesh transport, `wireguard-up` probes each node’s mesh SSH:

| Host type | `wait_for` timeout |
| --- | --- |
| Static public | **3s** |
| Roaming or Lima guest | **15s** |

## Bootstrap SSH paths

| Host type | Before / during `up` | After mesh up |
| --- | --- | --- |
| Static public | Public IP SSH (or mesh if already up) | `task ssh` / GHA over mesh |
| Non-Lima roaming | Cloudflare Tunnel → `bootstrap_ssh_host` | Mesh SSH |
| Lima guest | Lima-local `127.0.0.1` + `lima_nodes[].ssh_port` | Mesh SSH |

See [lima.md](lima.md) and [roaming-nodes.md](roaming-nodes.md).

## Host-key contract

`ssh_ed25519_sha256` on each host must match the VM’s `ssh_host_ed25519` key. `scripts/known-hosts.py` syncs `.state/<provider>/known_hosts` before `up`.

Lima guests: auto-filled by `lima-up ENV=<slug>` / `lima-host-fingerprints ENV=<slug>` (typically `dev-lima`). Static hosts: manual verification — see [setup-prod.md](setup-prod.md).

## Task entrypoints

Public (`task --list`); full reference in [tasks.md](tasks.md) and [task.mdx](../docs/src/content/docs/reference/task.mdx).

| Task | Action |
| --- | --- |
| `task up ENV=<env>` | Sync known_hosts, ensure vault keys, bring up mesh, install cluster stack |
| `task down ENV=<env> CONFIRM=down-<slug>` | Stop mesh + cluster; keeps vault and `.state/` |
| `task wg-status ENV=<env>` | Status playbook |
| `task wg-remove ENV=<env>` | Disconnect Mac controller only (nodes unchanged) |
| `task ssh ENV=<env> NODE=<host>` | SSH over mesh |

All require `provider.platform: public`. GHA mutations use Actions, not Task — see [gha-deploy.md](gha-deploy.md).

## State files

| Path | Content |
| --- | --- |
| `.state/<provider>/wireguard/scwg0.conf` | Mac controller config (`control_plane: mac`) |
| `.state/<provider>/known_hosts` | SSH aliases for bootstrap and mesh |
| Vault | WireGuard private keys per node (+ `macos` when used) |
| `/etc/supercompute/*` on nodes | Identity + dial sidecars |

## Firewall guidance

| Host | Inbound |
| --- | --- |
| Every dialable public static | UDP 51830 from roaming egress (wide enough for changing home IPs) |
| Static (bootstrap) | TCP 22 from operator `/32` if public SSH used |
| Roaming (home) | No inbound UDP 51830 |
| Mac | No inbound UDP 51830 required when a static relays Mac↔roaming |

## Related

- [vault.md](vault.md) — WireGuard key generation
- [gha-deploy.md](gha-deploy.md) — Actions control plane
- [tasks.md](tasks.md) — full task list
