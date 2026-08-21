# deploy/cloud

Provider automation for local Lima clusters and remote VPS production meshes.

| Guide | Audience |
| --- | --- |
| [docs/setup-local.md](docs/setup-local.md) | `local` / `cust-local` Lima on Apple Silicon |
| [docs/setup-prod.md](docs/setup-prod.md) | `prod` VPS WireGuard mesh |
| [docs/roaming-nodes.md](docs/roaming-nodes.md) | Dynamic-IP `roaming-N` peers (home lab) |

Shared entrypoints: `task setup`, vault tasks, and `task wg-*` (platform
dispatch by inventory `provider.platform`).
