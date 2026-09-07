# Troubleshooting

## `provider.platform=vps` or `lima` is refused

Rename inventory to `provider.platform: public`. Lima guests use `node_lima_guest: true` under a `public` mesh — see [lima.md](lima.md).

## Vault decrypt failures

- `project` in `hosts.yml` all.vars must match vault ID label and inner `vault_meta.project`.
- Restore `inventories/<provider>/.vault-pass` from backup (or recreate — [vault.md](vault.md)).
- See [vault.md](vault.md) for create commands.

## `up` fails on host-key fingerprint

- `ssh_ed25519_sha256` must be full `SHA256:…` from the host key.
- Lima guests: run `task lima-host-fingerprints ENV=dev-lima` (`lima-up` force-refreshes fingerprints after recreation).
- Non-Lima roaming: prove Cloudflare SSH first — see [roaming-nodes.md](roaming-nodes.md).

## `up` fails asserting `hostname`

- `inventories/<provider>/hosts.yml` → `all.vars` must define `project` and `hostname`
  before nodes can receive `/etc/supercompute/hosts.yml`.

## Mesh probe chooses bootstrap though mesh is up

- Roaming/Lima mesh SSH probe waits **15s**; static waits **3s**. A slow peer
  can force Lima/public bootstrap. Re-run `up` once the mesh is warm.

## Roaming mesh traffic fails

- **Every dialable public static** must accept **inbound UDP 51830** from a wide source (not only Mac `/32`).
- Roaming nodes must **not** use DynDNS as WireGuard `Endpoint`.
- Statics need `ip_forward` and FORWARD rules — applied by `wireguard_node` when roaming exists.
- After adding roaming peers, `wg syncconf` refreshes `AllowedIPs`.
- Check dial helper: `systemctl status supercompute-roaming-dial.timer`,
  `/etc/supercompute/public-endpoints.list`, `wg show`.

## GHA deploy fails

- Required secrets: `ANSIBLE_VAULT_PASSWORD`, `OPS_SSH_PRIVATE_KEY`.
- Do not Mac-`task up` a `control_plane: gha` inventory.
- Nodes need passwordless sudo for `ops`.
- See [gha-deploy.md](gha-deploy.md).

## Lima guest unreachable

- `task lima-status ENV=dev-lima`
- `limactl shell <guest-name>`
- Confirm `node_host_architecture: aarch64` (not `arm`).
- Do not set `bootstrap_ssh_host` on Lima guests.
- For a disposable dev-lima recovery, run `task dev-reset-lima CONFIRM=reset-dev-lima`, then
  `task lima-up ENV=dev-lima`, `task vault-init ENV=dev-lima`, and `task up ENV=dev-lima`.

## PowerDNS broke host DNS (apt fails after partial `up` or before `dev-reset`)

If `task up` fails at apt on a static node with empty DNS errors, PowerDNS from a
prior run may still hold port `53`. Run `task dev-reset CONFIRM=reset-dev` (retries
`task down ENV=dev` up to three times, 15 seconds apart) or
`task down ENV=dev CONFIRM=down-dev` manually.
New installs bind PowerDNS to the mesh address only so host `systemd-resolved` keeps working.

## `task down`

Requires `CONFIRM=down-<env>` matching `ENV`. Listed in `task --list`.

**Stop only** — keeps vault, `.state/<env>/`, and Lima guests. Re-run `task up` to restore.

For a full local factory reset (vault + `.state/` deleted, Lima destroyed when applicable), use `env-reset`, `dev-reset`, or `dev-reset-lima` instead. See [tasks.md](tasks.md).

## `up` / DNS issues

- `cluster_node` does not create DNS zones or application records.
- Set `hostname` in `hosts.yml` all.vars; Supercompute prepends `dns_prefix_*` from `group_vars/all/main.yml`.
- If the DNS is hosted on Cloudflare, do not enable the proxy orange icons.
- See [cluster.md](cluster.md) and [setup-prod.md](setup-prod.md).

## Starlight dev server shows stale content

Content collection pages may need a manual browser refresh after save; restart `bun run dev` if the sidebar slug errors after renames. Operator runbooks are in **`internal/`**, not auto-synced into Starlight unless copied.
