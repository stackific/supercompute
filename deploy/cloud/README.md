# deploy/cloud

Provider automation for local Lima clusters and remote VPS production meshes.

| Guide | Audience |
| --- | --- |
| [docs/setup-local.md](docs/setup-local.md) | `local` / `cust-local` Lima on Apple Silicon |
| [docs/setup-prod.md](docs/setup-prod.md) | `prod` VPS WireGuard mesh |
| [docs/encrypted-at-rest.md](docs/encrypted-at-rest.md) | `/srv/secure` fscrypt (`encryption_at_rest`) |

Shared entrypoints: `task setup`, vault tasks, `task wg-*`, and `task secure-*`
(platform dispatch by inventory `provider.platform` where applicable).
