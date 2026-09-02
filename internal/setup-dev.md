# Dev setup (public static hub)

The **`dev`** inventory is a `provider.platform: public` WireGuard mesh with one public static hub:

- **static-1** — Ubuntu 26.04 `node_host_architecture: x86_64` public endpoint (mesh hub)

Mesh CIDR defaults to **`10.217.80.0/24`** (disjoint from **`dev-lima`** at `10.217.81.0/24` and typical prod `10.217.79.0/24`).

For a Lima roaming guest on Apple Silicon, use **`dev-lima`** instead — see [lima.md](lima.md) and [Get started locally with a roaming node](../docs/src/content/docs/start-here/get-started-roaming-node.mdx).

`provider.platform: lima` and `provider.platform: vps` are refused — use `public`.

## Prerequisites

- macOS (controller)
- [Task](https://taskfile.dev/installation/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- WireGuard tools (`wg`, `wg-quick`)

```sh
brew install go-task/tap/go-task uv wireguard-tools
task setup
```

## 1. Prepare the static public host

Follow the same host prep as [setup-prod.md](setup-prod.md) (Ubuntu 26.04 amd64,
inventory SSH user, operator key, host-key fingerprint), then fill
`inventories/dev/hosts.yml` placeholders for `static-1`:

- `public_ip` — public IPv4
- `ssh_ed25519_sha256` — `SHA256:…` from the VM
- `private_address` — mesh IP in `10.217.80.0/24` (default `.11`)

Set `default_ssh_user` / `ssh_private_key_file` in
`inventories/dev/group_vars/all/main.yml` (same patterns as prod).

Allow inbound UDP **51830** on the static host widely enough for roaming peers.
During bootstrap, allow TCP **22** from the Mac `/32` if public SSH is still
required for the static host.

## 2. Vault and WireGuard mesh

```sh
task vault-init ENV=dev
task vault-edit ENV=dev   # set vault_database_url
task up ENV=dev
task wg-status ENV=dev
task ssh ENV=dev NODE=static-1
```

WireGuard for `dev` dispatches on `provider.platform: public` (same path as
prod). Tracked `dev` uses `control_plane: mac`. A single `task up` also installs
the cluster stack and `/etc/supercompute/*`.

## Reset dev

```sh
task dev-reset CONFIRM=reset-dev
task vault-init ENV=dev
task vault-edit ENV=dev
task up ENV=dev
```

`dev-reset` does **not** destroy Lima guests (`dev-lima` has its own reset). To stop without wiping vault or `.state/`, use `task down ENV=dev CONFIRM=down-dev` instead — see [tasks.md](tasks.md).

## Sample mesh addresses

The tracked `dev` inventory uses `10.217.80.0/24`:

| Role | Address |
| --- | --- |
| Mac controller | `10.217.80.1` (`node_controller_address`) |
| GHA CI peer (unused unless Actions) | `10.217.80.254` (`node_ci_address`) |
| `static-1` hub | `10.217.80.11` (`private_address`) |

Test the controller address from the static hub:

```sh
ping -c 10 -I scwg0 10.217.80.1
```

## Operator checklist

1. Prepare public `static-1` and fill inventory placeholders (including fingerprint).
2. `task vault-init ENV=dev`; `task vault-edit ENV=dev` (set `vault_database_url`); `task up ENV=dev`.
3. Spot-check mesh SSH with `task ssh ENV=dev NODE=static-1`.
