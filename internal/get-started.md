# Get started

Minimal path from a fresh clone to a working **`dev`** mesh (one public static hub). For Lima roaming on Apple Silicon, use **`dev-lima`** — [Get started locally with a roaming node](../docs/src/content/docs/start-here/get-started-roaming-node.mdx).

## 1. Install tools

```sh
brew install go-task/tap/go-task uv wireguard-tools
```

For **`dev-lima`**, also install Lima — see [lima.md](lima.md).

See [prerequisites.md](prerequisites.md) for details.

## 2. Bootstrap automation

From the worktree root:

```sh
task setup
```

## 3. Prepare `static-1`

1. Create Ubuntu 26.04 `x86_64` on a provider with a public IP.
2. Follow host prep in [setup-prod.md](setup-prod.md) (SSH user, operator key, sudo).
3. Fill `inventories/dev/hosts.yml` placeholders for `static-1`:
   - `public_ip`
   - `ssh_ed25519_sha256`
4. Open UDP **51830** on the static host for roaming egress.

## 4. Vault and mesh

```sh
task vault-init ENV=dev
task vault-edit ENV=dev   # set vault_database_url
task up ENV=dev
task wg-status ENV=dev
task ssh ENV=dev NODE=static-1
```

`task up` brings up WireGuard **and** installs the cluster stack (gVisor, Docker, Caddy reverse-proxying `sc-app.`→`sc` and `sc-api.`→`supercompute`, PowerDNS), writes `/etc/supercompute/*` on nodes. See [cluster.md](cluster.md) and [wireguard.md](wireguard.md).

## Reset dev

For a destructive local reset, including the dev vault and password:

```sh
task dev-reset CONFIRM=reset-dev
task vault-init ENV=dev
task vault-edit ENV=dev
task up ENV=dev
```

`dev-reset` runs `task down ENV=dev` (retried), disconnects the Mac mesh, deletes `.state/dev`, and removes the dev vault/password. It does **not** destroy Lima (`dev-lima` is separate). The remote VM is unchanged (`ops`, keys, firewall).

To stop without wiping vault or `.state/`, use `task down ENV=dev CONFIRM=down-dev` — then `task up ENV=dev` restores the mesh. See [tasks.md](tasks.md).

## Next steps

| Goal | Document |
| --- | --- |
| Full `dev` walkthrough | [setup-dev.md](setup-dev.md) |
| Lima roaming guest | [lima.md](lima.md), [Get started locally with a roaming node](../docs/src/content/docs/start-here/get-started-roaming-node.mdx) |
| Production mesh | [setup-prod.md](setup-prod.md) |
| GHA-managed deploy | [gha-deploy.md](gha-deploy.md) |
| Home lab roaming (Cloudflare) | [roaming-nodes.md](roaming-nodes.md) |
| Task reference | [tasks.md](tasks.md) |
