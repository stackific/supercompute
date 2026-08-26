# Dev setup (public mesh + Lima roaming guest)

The `dev` inventory is a `provider.platform: public` WireGuard mesh with:

- **static-1** — Ubuntu 26.04 `node_host_architecture: x86_64` public endpoint (mesh hub)
- **roaming-1** — Lima guest (`node_lima_guest: true`, `node_host_architecture: aarch64` — not `arm`), WireGuard roaming that dials the hub

Mesh CIDR defaults to **`10.217.80.0/24`** (disjoint from typical prod `10.217.79.0/24`).

`provider.platform: lima` and `provider.platform: vps` are refused — use
`public`. Lima is only a guest factory for hosts marked `node_lima_guest: true`.

## Prerequisites

- macOS on Apple Silicon (controller + Lima)
- [Task](https://taskfile.dev/installation/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [Lima](https://lima-vm.io/docs/installation/) (pinned version in inventory)
- WireGuard tools (`wg`, `wg-quick`)

```sh
brew install go-task/tap/go-task uv wireguard-tools lima
task setup
```

`task setup` installs the locked Ansible venv. On macOS it also installs
`cloudflared` when missing — needed only for **non-Lima** roaming (see
[roaming-nodes.md](roaming-nodes.md)), not for `node_lima_guest` hosts.

## 1. Prepare the static public host

Follow the same host prep as [setup-prod.md](setup-prod.md) (Ubuntu 26.04 amd64,
inventory SSH user, operator key, host-key fingerprint), then fill
`inventories/dev/hosts.yml` placeholders for `static-1`:

- `wireguard_endpoint` — public IPv4
- `ssh_host_ed25519_sha256` — `SHA256:…` from the VM
- `wireguard_address` — mesh IP in `10.217.80.0/24` (default `.11`)

Set `default_ssh_user` / `ssh_private_key_file` in
`inventories/dev/group_vars/all/main.yml` (same patterns as prod).

Allow inbound UDP **51830** on the static host widely enough for roaming (the
Lima guest’s public egress changes). During bootstrap, allow TCP **22** from the
Mac `/32` if public SSH is still required for the static host.

## 2. Create the Lima roaming guest

```sh
task lima-up
task lima-status
```

`lima-up` operates only on hosts with `node_lima_guest: true` (here `roaming-1`).
Runtime home:

```text
~/.lima/.<project>-dev
```

Tracked definitions live under `.state/dev/lima/`. Destroy with:

```sh
task lima-destroy CONFIRM=destroy-lima-dev
```

### Guest host-key fingerprints

`lima-up` auto-fills `ssh_host_ed25519_sha256` for every
`node_lima_guest` host (Lima-local SSH scan → `inventories/<provider>/hosts.yml`).
Re-run capture alone with:

```sh
task lima-host-fingerprints
```

After `lima-destroy` + recreate, overwrite the previous value with `--force`:

```sh
uv run --locked python scripts/lima-host-fingerprints.py --provider dev --force
```

**`static-1` (and any non-Lima host) stays manual** — record
`ssh_host_ed25519_sha256` yourself, same as [setup-prod.md](setup-prod.md).
Do **not** set `bootstrap_ssh_host` or `wireguard_endpoint` on Lima
guests.

## 3. Bootstrap split (Lima-local vs Cloudflare)

Lima guests join WireGuard by dialing the static hub’s public `Endpoint`
(`public-ip:51830`). Ansible bootstrap SSH to those guests is **Lima-local**
(`127.0.0.1` + `lima_nodes[].ssh_port`, identity `LIMA_HOME/_config/user`) —
not Cloudflare Tunnel / `cloudflared`.

Cloudflare Tunnel remains for **non-Lima** prod roaming only — see
[roaming-nodes.md](roaming-nodes.md).

## 4. Vault and WireGuard mesh

```sh
task vault-init PROVIDER=dev
# fill static-1 placeholders first (Lima guest fingerprints come from lima-up)
task up PROVIDER=dev
task wg-status PROVIDER=dev
task ssh PROVIDER=dev NODE=static-1
task ssh PROVIDER=dev NODE=roaming-1
```

WireGuard for `dev` dispatches on `provider.platform: public` (same path as
prod). The Mac never dials the Lima guest’s UDP port for the mesh.

Optional cluster services after the mesh is up:

```sh
task up PROVIDER=dev
```

## Reset dev

Use the dev-only reset task instead of manually combining Lima destruction,
controller WireGuard cleanup, state removal, and Vault removal:

```sh
task dev-reset CONFIRM=reset-dev
task vault-init PROVIDER=dev
task lima-up
task up PROVIDER=dev
```

It deletes the dev Vault/password, `.state/dev`, Lima guests, and their
dedicated runtime home, but leaves the remote static host intact.

## Architecture rules

| Host | `node_host_architecture` | Bootstrap SSH |
| --- | --- | --- |
| static / non-Lima | `x86_64` | public endpoint (or Cloudflare if `wireguard_roaming`) |
| `node_lima_guest: true` | `aarch64` (**not** `arm`) | Lima-local SSH |

Inventory default is `x86_64`; Lima guests override to `aarch64` on the host
(Ansible asserts this — `arm` fails).

## Sample mesh addresses

The tracked `dev` inventory uses `10.217.80.0/24`:

| Role | Address |
| --- | --- |
| Mac controller | `10.217.80.1` (`wireguard_controller_address`) |
| `static-1` hub | `10.217.80.11` (`wireguard_address`) |
| `roaming-1` Lima guest | `10.217.80.21` (`wireguard_address`) |

Test the controller address from both node types:

```sh
# On static-1: direct WireGuard peer to the Mac controller.
ping -c 10 -I scwg0 10.217.80.1

# On roaming-1: relayed through static-1 to the Mac controller.
ping -c 10 -I scwg0 10.217.80.1

# < 20 ms: Excellent (same metro / nearby region)
# 20–50 ms: Very good (typical same-country / nearby DC)
# 50–100 ms: Fine for SSH, Ansible, mesh ops
# 100–200 ms: Usable; interactive work has noticeable lag
# > 200 ms: Cross-ocean or relayed path; usable for automation, poor for snappy shells
```

## Operator checklist

1. Prepare public `static-1` and fill inventory placeholders (including its
   fingerprint by hand).
2. `task lima-up` — only `node_lima_guest` hosts; auto-fills their
   `ssh_host_ed25519_sha256`.
3. Prove `limactl shell roaming-1`.
4. `task vault-init PROVIDER=dev`; `task up PROVIDER=dev`.
5. Optional: `task up PROVIDER=dev`.
