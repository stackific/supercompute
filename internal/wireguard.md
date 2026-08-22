# WireGuard mesh

Production meshes use interface **`scwg0`**, UDP port **`51830`** (inventory: `prod_wireguard_listen_port`), and addresses in the inventory mesh CIDR.

## Participants

| Party | Role |
| --- | --- |
| macOS controller | WireGuard peer at `prod_wireguard_controller_address` (usually `.1`) |
| Static public hosts | Stable `prod_wireguard_endpoint`; mesh hub when roaming exists |
| Roaming hosts | `wireguard_roaming: true`; dial hub; no inbound UDP 51830 at home |

Inventory hostnames: `static-1`, `static-2`, … and `roaming-1`, `roaming-2`, … (not `home-*` or `prod-*` prefixes).

## Roaming rules

1. **Roaming nodes always initiate** WireGuard to the static hub `Endpoint`.
2. Stable peers (Mac, static hosts) **do not dial** roaming nodes for mesh traffic.
3. **No DynDNS** or public hostname as WireGuard `Endpoint` for roaming peers.
4. **No inbound UDP 51830** port-forward on home routers for roaming nodes.

Cloudflare Tunnel carries **SSH bootstrap only**; it does not carry `scwg0` UDP.

## Static hub (Mac ↔ roaming)

When any roaming node exists, `prod-wireguard-up` selects the first static host as **`prod_wireguard_hub`** (typically `static-1`).

The hub:

- Enables `net.ipv4.ip_forward`
- Adds iptables `FORWARD` rules for WireGuard peers
- Holds hub peer `AllowedIPs` including the Mac controller and other roaming `/32`s

After WireGuard starts, the role runs `wg-quick strip` + `wg syncconf` so hub `AllowedIPs` updates without a full interface restart (systemd `started` does not reload `AllowedIPs`).

Spoke-to-spoke roaming traffic routes through the hub; roaming peers do not peer directly.

## Bootstrap SSH paths

| Host type | Before / during `up` | After mesh up |
| --- | --- | --- |
| Static public | Public IP SSH (or mesh if already up) | `task ssh` over mesh |
| Non-Lima roaming | Cloudflare Tunnel → `prod_bootstrap_ssh_host` | Mesh SSH |
| Lima guest | Lima-local `127.0.0.1` + `lima_nodes[].ssh_port` | Mesh SSH |

See [lima.md](lima.md) and [roaming-nodes.md](roaming-nodes.md).

## Host-key contract

`prod_ssh_host_ed25519_sha256` on each host must match the VM’s `ssh_host_ed25519` key. `scripts/prod-known-hosts.py` syncs `.state/<provider>/known_hosts` before `up`.

Lima guests: auto-filled by `lima-up` / `lima-host-fingerprints`. Static hosts: manual verification — see [setup-prod.md](setup-prod.md).

## Task entrypoints

| Task | Action |
| --- | --- |
| `task up PROVIDER=<slug>` | Sync known_hosts, ensure vault keys, bring up mesh, install cluster stack |
| `task wg-status PROVIDER=<slug>` | Status playbook |
| `task wg-remove PROVIDER=<slug>` | Disconnect Mac controller only (nodes unchanged) |
| `task ssh PROVIDER=<slug> NODE=<host>` | SSH over mesh |

All require `provider.platform: public`.

## State files

| Path | Content |
| --- | --- |
| `.state/<provider>/wireguard/scwg0.conf` | Mac controller config |
| `.state/<provider>/known_hosts` | SSH aliases for bootstrap and mesh |
| Vault | WireGuard private keys per node |

## Firewall guidance

| Host | Inbound |
| --- | --- |
| Static hub | UDP 51830 from roaming egress (wide enough for changing home IPs) |
| Static hub (bootstrap) | TCP 22 from Mac public `/32` if public SSH used |
| Roaming (home) | No inbound UDP 51830 |
| Mac | No inbound UDP 51830 required when hub routes Mac↔roaming |

## Related

- [vault.md](vault.md) — WireGuard key generation
- [tasks.md](tasks.md) — full task list
