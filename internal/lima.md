# Lima guests

Lima provides Ubuntu guests on the Mac for **`node_lima_guest: true`** hosts. Lima is **not** a `provider.platform`; it is a guest factory under `provider.platform: public`.

Use inventory slug **`dev-lima`** for the tracked Lima development environment.

## Scope

| Task | Targets |
| --- | --- |
| `lima-up ENV=<slug>` | Hosts with `node_lima_guest: true` in that inventory |
| `lima-status ENV=<slug>` | Same |
| `lima-destroy ENV=<slug>` | Internal — destroy guests (`env-reset` calls this) |
| `lima-host-fingerprints ENV=<slug>` | Internal — fingerprint capture (`lima-up` runs `--force`) |

The tracked guest is **`roaming-1`** under `inventories/dev-lima/`.

## Runtime vs tracked state

| Location | Content |
| --- | --- |
| `~/.lima/.<project>-<provider>/` | Lima VM runtime (`LIMA_HOME` / `lima_runtime_home`) |
| `.state/<provider>/lima/` | Instance definitions managed by Ansible |
| `inventories/<provider>/group_vars/all/main.yml` | `lima_nodes` port/MAC mapping |

`scripts/lima-runtime-home.sh` resolves `LIMA_HOME` for playbooks and fingerprint capture.

## Architecture

Lima guests run **`aarch64`** Ubuntu (`node_host_architecture: aarch64`). Inventory default `x86_64` applies to non-Lima hosts. Ansible refuses `arm`.

Image defaults in `dev-lima` inventory point at Ubuntu 26.04 arm64 template.

## WireGuard behavior

Lima roaming guests are **`roaming: true`** peers:

- Build-up: they dial the first static hub's **`public_ip`** (`public-ip:51830`).
- Day-2: they use the same **`supercompute-roaming-dial`** helper as non-Lima roaming (`/etc/supercompute/*`, hourly timer).
- They do **not** have `public_ip` in inventory.
- The Mac does not need inbound UDP 51830 for Mac↔guest mesh (a static forwards when applicable).

Lima guests join the mesh through the same `wireguard-up` path as other nodes (`provider.platform: public` + `node_lima_guest`).

## Bootstrap SSH

Ansible reaches Lima guests via **Lima-local SSH**:

- Host: `127.0.0.1`
- Port: `lima_nodes[].ssh_port` (for example `61222` on `dev-lima`)
- Identity: `LIMA_HOME/_config/user`

**Cloudflare Tunnel is not used** for Lima guests. See [roaming-nodes.md](roaming-nodes.md) for non-Lima roaming.

## Host-key fingerprints

After `lima-up`, fingerprints are written into `hosts.yml` automatically. To re-capture without recreating guests (internal task):

```sh
task lima-host-fingerprints ENV=dev-lima
```

Or via script with `--force` after guest recreate:

```sh
uv run --locked python scripts/lima-host-fingerprints.py --provider dev-lima --force
```

**`static-1` and other non-Lima hosts stay manual.**

## Destroy and reset

Lima destroy is internal (`task lima-destroy`); use **`dev-reset-lima`** for a full factory reset, or re-run **`lima-up`** after a manual guest recreate.

## Typical sequence

```sh
task lima-up ENV=dev-lima
task lima-status ENV=dev-lima
limactl shell roaming-1   # operator smoke test
task vault-init ENV=dev-lima
task up ENV=dev-lima
task ssh ENV=dev-lima NODE=roaming-1
```

To **stop** without wiping vault or Lima: `task down ENV=dev-lima CONFIRM=down-dev-lima`, then `task up ENV=dev-lima` to restore.

## Full dev-lima reset

`dev-reset-lima` (alias `env-reset ENV=dev-lima`) factory-resets back to pre-`lima-up`: runs `task down ENV=dev-lima`, destroys Lima guests and runtime home (`~/.lima/.<project>-dev-lima`), deletes `.state/dev-lima`, and deletes the dev-lima vault/password.

```sh
task dev-reset-lima CONFIRM=reset-dev-lima
task lima-up ENV=dev-lima
task vault-init ENV=dev-lima
task up ENV=dev-lima
```

**`dev-reset`** does not touch Lima — it only resets the static-only `dev` environment.

## Related

- [setup-dev.md](setup-dev.md) — `dev` static hub walkthrough
- [inventories.md](inventories.md) — `lima_nodes` structure
