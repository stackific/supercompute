# Troubleshooting

## `provider.platform=vps` or `lima` is refused

Rename inventory to `provider.platform: public`. Lima guests use `node_lima_guest: true` under a `public` mesh — see [lima.md](lima.md).

## Vault decrypt failures

- `cloud_name` in `cloud.yml` must match vault ID label and inner `cloud_vault.cloud_name`.
- Restore `inventories/<provider>/.vault-pass` from backup.
- See [vault.md](vault.md).

## `up` fails on host-key fingerprint

- `cloud_ssh_host_ed25519_sha256` must be full `SHA256:…` from the host key.
- Lima guests: run `task lima-host-fingerprints` (it targets dev; `lima-up`
  force-refreshes fingerprints after recreation).
- Non-Lima roaming: prove Cloudflare SSH first — see [roaming-nodes.md](roaming-nodes.md).

## Roaming mesh traffic fails

- Static hub must accept **inbound UDP 51830** from wide source (not only Mac `/32`).
- Roaming nodes must **not** use DynDNS as WireGuard `Endpoint`.
- Hub needs `ip_forward` and FORWARD rules — applied by `cloud_wireguard_node`.
- After adding roaming peers, hub uses `wg syncconf` to refresh `AllowedIPs`.

## Lima guest unreachable

- `task lima-status`
- `limactl shell <guest-name>`
- Confirm `node_host_architecture: aarch64` (not `arm`).
- Do not set `cloud_bootstrap_ssh_host` on Lima guests.
- For a disposable dev recovery, run `task dev-reset CONFIRM=reset-dev`, then
  `task vault-init PROVIDER=dev`, `task lima-up`, and `task up PROVIDER=dev`.

## `up` / DNS issues

- `cluster_node` does not create DNS zones or application records.
- Set the externally managed nameserver hostname with `cloud_nameserver_hostname`
  in `cloud.yml` when recording a deployment's DNS delegation.
- See [cluster.md](cluster.md) and [setup-prod.md](setup-prod.md).

## Starlight dev server shows stale content

Content collection pages may need a manual browser refresh after save; restart `bun run dev` if the sidebar slug errors after renames. Operator runbooks are in **`internal/`**, not auto-synced into Starlight unless copied.
