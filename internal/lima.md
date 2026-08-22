# Lima guests

Lima provides Ubuntu guests on the Mac for **`node_lima_guest: true`** hosts. Lima is **not** a `provider.platform`; it is a guest factory under `provider.platform: public`.

## Scope

| Task | Targets |
| --- | --- |
| `lima-up` | Hosts with `node_lima_guest: true` in the active inventory |
| `lima-status` | Same |
| `lima-destroy` | Same (requires `CONFIRM`) |
| `lima-host-fingerprints` | Same |

`PROVIDER=dev` with `roaming-1` is the tracked example.

## Runtime vs tracked state

| Location | Content |
| --- | --- |
| `~/.lima/.<deployment_name>-<provider>/` | Lima VM runtime (`LIMA_HOME` / `lima_runtime_home`) |
| `.state/<provider>/lima/` | Instance definitions managed by Ansible |
| `inventories/<provider>/group_vars/all/main.yml` | `lima_nodes` port/MAC mapping |

`scripts/lima-runtime-home.sh` resolves `LIMA_HOME` for playbooks and fingerprint capture.

## Architecture

Lima guests run **`aarch64`** Ubuntu (`node_host_architecture: aarch64`). Inventory default `x86_64` applies to non-Lima hosts. Ansible refuses `arm`.

Image defaults in `dev` inventory point at Ubuntu 26.04 arm64 template.

## WireGuard behavior

Lima roaming guests are **`wireguard_roaming: true`** peers:

- They dial the static hub’s **`prod_wireguard_endpoint`** (`public-ip:51830`).
- They do **not** have `prod_wireguard_endpoint` in inventory.
- The Mac does not need inbound UDP 51830 for Mac↔guest mesh (hub forwards when applicable).

## Bootstrap SSH

Ansible reaches Lima guests via **Lima-local SSH**:

- Host: `127.0.0.1`
- Port: `lima_nodes[].ssh_port` (for example `61221`)
- Identity: `LIMA_HOME/_config/user`

**Cloudflare Tunnel is not used** for Lima guests. See [roaming-nodes.md](roaming-nodes.md) for non-Lima roaming.

## Host-key fingerprints

After `lima-up`, `scripts/lima-host-fingerprints.py` scans each guest and writes `prod_ssh_host_ed25519_sha256` into `hosts.yml`.

```sh
task lima-host-fingerprints PROVIDER=dev
```

After destroy + recreate:

```sh
uv run --locked python scripts/lima-host-fingerprints.py --provider dev --force
```

**`static-1` and other non-Lima hosts stay manual.**

## Destroy confirmation

```sh
task lima-destroy PROVIDER=dev CONFIRM=destroy-lima-dev
```

`CONFIRM` must be exactly `destroy-lima-<inventory_slug>`.

## Typical sequence

```sh
task lima-up PROVIDER=dev
task lima-status PROVIDER=dev
limactl shell roaming-1   # operator smoke test
task up PROVIDER=dev
task ssh PROVIDER=dev NODE=roaming-1
```

## Related

- [setup-dev.md](setup-dev.md) — full dev walkthrough
- [inventories.md](inventories.md) — `lima_nodes` structure
