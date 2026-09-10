# Get started

Minimal path from a fresh clone to a working **`dev`** mesh (one public static hub). For Lima roaming on a Mac, use **`dev-lima`** — [Adding a node roaming on a Mac](../docs/src/content/docs/guides/adding-node-roaming-on-a-mac.mdx).

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

`task setup` installs the locked Ansible venv and fetches the SHA-pinned rathole Linux amd64 binary into `.vendor/rathole/` (copied to Ubuntu nodes by Ansible; unused until a non-Lima roaming host exists).

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

`task up` brings up WireGuard **and** installs the cluster stack (gVisor, Docker, Caddy reverse-proxying `sc_app`→`sc` and `sc_api`→`supercompute`, PowerDNS), writes `/etc/supercompute/*` on nodes, and passes `SC_API` to `sc` plus `SC_APP` / `SC_NS` / `SC_APPS` to `supercompute`. See [cluster.md](cluster.md) and [wireguard.md](wireguard.md).

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
| Lima roaming guest | [lima.md](lima.md), [Adding a node roaming on a Mac](../docs/src/content/docs/guides/adding-node-roaming-on-a-mac.mdx) |
| Production mesh | [setup-prod.md](setup-prod.md) |
| GHA-managed deploy | [gha-deploy.md](gha-deploy.md) |
| Home lab roaming (rathole) | [roaming-nodes.md](roaming-nodes.md) |
| Task reference | [tasks.md](tasks.md) |
