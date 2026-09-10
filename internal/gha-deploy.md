# GitHub Actions deploy (control_plane=gha)

Manual `workflow_dispatch` workflow [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) brings up or tears down a provider **without** a Mac controller peer. The Mac operator path (`task up`, LaunchDaemon, Lima) stays available for other inventories.

## When to use which path

| Path | Entry | Mac WG peer | Lima | Mutations |
| --- | --- | --- | --- | --- |
| Mac | `task up ENV=<env>` | yes (`.1`) | optional | from the Mac |
| GHA | Actions → Deploy | no | no | from the workflow only |

Do **not** run Mac `task up` against a GHA-managed inventory (`control_plane: gha`).

## Inventory

Set in `inventories/<slug>/group_vars/all/main.yml`:

```yaml
control_plane: gha
node_ci_address: 10.217.79.254   # unique IP in that provider's mesh CIDR (dev often uses .254 in 10.217.80.0/24)
node_forward_on_all_statics: true  # every public static can relay day-2 dial
```

Commit `hosts.yml` and encrypted `group_vars/all/vault.yml`. Keep `.vault-pass` out of git. The workflow also writes `.state/<provider>/gha-extra-vars.yml` (`control_plane: gha` plus optional Mac pubkey).

The encrypted vault must contain `vault_database_url` (`postgresql://REPLACE_WITH_USER:PASSWORD@HOST:5432/DATABASE` until replaced via `task vault-edit` before commit) and `vault_database_secret` (created by `task vault-init`). CI decrypts both with repository secret `ANSIBLE_VAULT_PASSWORD` — there is no separate `DATABASE_URL` Actions secret.

## Ephemeral runner mesh peer

`up` / `verify` briefly join the GitHub-hosted **runner VM** (`ubuntu-latest`) to the mesh as `node_ci_address`, then remove that peer when the job ends. That runner filesystem (including generated CI WireGuard keys under `.state/<provider>/gha-peer/`) is discarded with the runner — **not** your static/roaming/Lima nodes. A later workflow run generates a new CI keypair, re-adds the peer, works, and removes it again without tearing down the existing node mesh.

## Log hygiene

- Repo secrets are written to mode-`0600` files; values are not echoed.
- Generated CI keys and optional Mac pubkey are registered with `::add-mask::`.
- Ansible receives `control_plane` / keys via `--extra-vars @file` (not argv literals).
- `gha-mesh-peer` play uses play-level `no_log: true`.

## Repository secrets

| Secret | Required | Purpose |
| --- | --- | --- |
| `ANSIBLE_VAULT_PASSWORD` | yes | Exact contents of `inventories/<slug>/.vault-pass` |
| `OPS_SSH_PRIVATE_KEY` | yes | Private key for `ops` on nodes |
| `MAC_OPERATOR_SSH_PUBLIC_KEY` | no | If set, installed into `/home/ops/.ssh/authorized_keys` |

Non-Lima roaming uses rathole on the static hub (inbound **TCP 2333**). The workflow fetches the SHA-pinned rathole binary the same way as `task setup`. It does **not** replace first-time client install: from a Mac that has `.vault-pass` and the ops key, run `task rathole-client-bootstrap ENV=<env> NODE=<roaming-host>`, copy the script onto the VM (console/LAN), prove jump SSH, and **commit `vault.yml`** if Noise keys/tokens were just created. Then Deploy `up`. First known-hosts scan skips roaming until the hub jump is listening (`--skip-non-lima-roaming`); `wireguard-up` refreshes those keys through the jump. The runner jumps through the hub the same way as a Mac (`127.0.0.1` + last octet of `private_address`). `down` leaves rathole in place.

Nodes must allow passwordless `sudo` for `ops` (GHA cannot prompt for a become password).

## Run

1. Actions → **Deploy** → Run workflow.
2. Inputs: `env`, `action` (`up` / `down` / `verify`), and for `down` set `confirm` to `down-<env>`.

`up` flow: known-hosts → ensure-secrets → validate deployment config → `wireguard-up` (skips Mac controller and Mac mesh SSH proof; node↔node proof uses bootstrap recovery SSH until the runner is on-mesh) → ephemeral CI mesh peer → runner mesh SSH proof → `cluster-up` → remove CI peer.

`verify` flow: known-hosts → ephemeral CI mesh peer → runner mesh SSH proof → `verify.yml` → remove CI peer.

## Shared post-build roaming dial

After WireGuard is up, every roaming node (Mac or GHA path) runs `/usr/local/sbin/supercompute-roaming-dial`, which uses `shuf` to pick one public static from `/etc/supercompute/public-endpoints.list` and `wg set` to make that peer the active Endpoint/transit. A systemd timer (`roaming_dial_timer_on_calendar`, default **hourly**) re-runs it. Build-up still pins the first static hub for a deterministic join. With `node_forward_on_all_statics: true`, every public static can forward.

## Related

- [vault.md](vault.md) — creating `.vault-pass`
- [wireguard.md](wireguard.md) — mesh behavior
- [roaming-nodes.md](roaming-nodes.md) — rathole bootstrap for home-lab nodes
- [setup-prod.md](setup-prod.md) — production inventory shape
