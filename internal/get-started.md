# Get started

Minimal path from a fresh clone to a working **`dev`** mesh. For production or Cloudflare roaming, use the dedicated runbooks.

## 1. Install tools

```sh
brew install go-task/tap/go-task uv wireguard-tools lima
```

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
   - `wireguard_endpoint`
   - `ssh_host_ed25519_sha256`
4. Open UDP **51830** on the static host for roaming egress.

## 4. Lima roaming guest

```sh
task lima-up
task lima-status
```

`lima-up` auto-fills `ssh_host_ed25519_sha256` for `node_lima_guest` hosts.

## 5. Vault and mesh

```sh
task vault-init PROVIDER=dev
task up PROVIDER=dev
task wg-status PROVIDER=dev
task ssh PROVIDER=dev NODE=static-1
task ssh PROVIDER=dev NODE=roaming-1
```

## Reset dev

For a destructive local reset, including the dev vault and password:

```sh
task dev-reset CONFIRM=reset-dev
task vault-init PROVIDER=dev
task lima-up
task up PROVIDER=dev
```

`dev-reset` does not change the remote static host. It removes Lima guests,
their dedicated runtime home, `.state/dev`, and the dev vault/password.

## 6. Optional cluster stack

```sh
task up PROVIDER=dev
```

Installs gVisor, Docker Engine, Caddy, and PowerDNS on deployment nodes. See
[cluster.md](cluster.md).

## Next steps

| Goal | Document |
| --- | --- |
| Full `dev` walkthrough | [setup-dev.md](setup-dev.md) |
| Production mesh | [setup-prod.md](setup-prod.md) |
| Home lab roaming (Cloudflare) | [roaming-nodes.md](roaming-nodes.md) |
| Task reference | [tasks.md](tasks.md) |
