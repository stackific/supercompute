# Provider automation (worktree root)

Provider automation for public-endpoint WireGuard meshes. **`dev`** is one static hub; **`dev-lima`** adds a Lima roaming guest on Apple Silicon.

**Operator documentation:** [`internal/`](internal/README.md) (runbooks and reference).

Public docs site (Starlight): `cd docs && bun install && bun run dev`.

| Guide | Audience |
| --- | --- |
| [internal/setup-dev.md](internal/setup-dev.md) | `ENV=dev` — public static hub |
| [internal/lima.md](internal/lima.md) | `ENV=dev-lima` — static hub + Lima `node_lima_guest` |
| [internal/setup-prod.md](internal/setup-prod.md) | Operator `prod` mesh (two static nodes) |
| [internal/roaming-nodes.md](internal/roaming-nodes.md) | Non-Lima roaming via Cloudflare Tunnel SSH |

Public Task entrypoints (`task --list`): `setup`, `up`, `down`, `env-reset`, `dev-reset`, `dev-reset-lima`, `vault-init`, `vault-edit`, `wg-status`, `wg-remove`, `ssh`, `lima-up`, `lima-status`. See [docs task reference](docs/src/content/docs/reference/task.mdx).
