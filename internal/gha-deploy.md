# GitHub Actions deploy (control_plane=gha)

Manual `workflow_dispatch` workflow [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) brings up or tears down a provider **without** a Mac controller peer. The Mac operator path (`task up`, LaunchDaemon, Lima) stays available for other inventories.

## When to use which path

| Path | Entry | Mac WG peer | Lima | Mutations |
| --- | --- | --- | --- | --- |
| Mac | `task up PROVIDER=<slug>` | yes (`.1`) | optional | from the Mac |
| GHA | Actions → Deploy | no | no | from the workflow only |

Do **not** run Mac `task up` against a GHA-managed inventory (`control_plane: gha`).

## Inventory

Set in `inventories/<slug>/group_vars/all/main.yml`:

```yaml
control_plane: gha
wireguard_ci_address: 10.217.79.254   # ephemeral runner mesh IP (unique in CIDR)
```

Commit `hosts.yml` and encrypted `group_vars/all/vault.yml`. Keep `.vault-pass` out of git.

## Repository secrets

| Secret | Required | Purpose |
| --- | --- | --- |
| `ANSIBLE_VAULT_PASSWORD` | yes | Exact contents of `inventories/<slug>/.vault-pass` |
| `OPS_SSH_PRIVATE_KEY` | yes | Private key for `ops` on nodes |
| `MAC_OPERATOR_SSH_PUBLIC_KEY` | no | If set, installed into `/home/ops/.ssh/authorized_keys` |

Cloudflare Access / tunnels are **operator-owned** and outside this project. Non-Lima roaming may still use `bootstrap_ssh_host` in inventory; configure the tunnel yourself. This workflow does not store Cloudflare API tokens.

Nodes must allow passwordless `sudo` for `ops` (GHA cannot prompt for a become password).

## Run

1. Actions → **Deploy** → Run workflow.
2. Inputs: `provider`, `action` (`up` / `down` / `verify`), and for `down` set `confirm` to `down-<provider>`.

`up` flow: known-hosts → vault WG keys → `wireguard-up` with `control_plane=gha` → ephemeral CI mesh peer → `cluster-up` → remove CI peer.

## Shared post-build roaming dial

After WireGuard is up, every roaming node (Mac or GHA path) runs `/usr/local/sbin/supercompute-roaming-dial`, which uses `shuf` to pick one public static from `/etc/supercompute/public-endpoints.list` and `wg set` to make that peer the active Endpoint/transit. A systemd timer re-runs it periodically. Build-up still pins the first static hub for a deterministic join.

## Related

- [vault.md](vault.md) — creating `.vault-pass`
- [wireguard.md](wireguard.md) — mesh behavior
- [setup-prod.md](setup-prod.md) — production inventory shape
