# Provider automation (worktree root)

Provider automation for public-endpoint WireGuard meshes and optional Lima
roaming guests under `PROVIDER=dev`.

**Operator documentation:** [`internal/`](internal/README.md) (runbooks and reference).

Public docs site (Starlight): `cd docs && bun install && bun run dev`.

| Guide | Audience |
| --- | --- |
| [internal/setup-dev.md](internal/setup-dev.md) | `dev` / `provider.platform: public` + Lima `node_lima_guest` |
| [internal/setup-prod.md](internal/setup-prod.md) | Operator `prod` mesh (gitignored inventory; restore from backup) |
| [internal/roaming-nodes.md](internal/roaming-nodes.md) | Non-Lima roaming via Cloudflare Tunnel SSH |

Shared entrypoints: `task setup`, vault tasks, `task lima-*`, `task up` / `task down`,
`task wg-status`, `task ssh` (`provider.platform: public` only).
