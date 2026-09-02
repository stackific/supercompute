# Internal operator documentation

Markdown runbooks and reference at the **worktree root** (`internal/`). The public Starlight site lives in `docs/` — see [docs-site.md](docs-site.md).

## Start here

| Document | Purpose |
| --- | --- |
| [overview.md](overview.md) | What Supercompute is and how the automation fits together |
| [get-started.md](get-started.md) | Fast path from clone to a working `dev` mesh |
| [prerequisites.md](prerequisites.md) | Host tools, `hosts.yml`, SSH identity |

## Runbooks

| Document | Audience |
| --- | --- |
| [setup-dev.md](setup-dev.md) | `ENV=dev` — public static hub (`control_plane: mac`) |
| [lima.md](lima.md) | `ENV=dev-lima` — Lima `node_lima_guest` roaming on Apple Silicon |
| [setup-prod.md](setup-prod.md) | Operator `prod` mesh (two static nodes) |
| [gha-deploy.md](gha-deploy.md) | Manual GitHub Actions deploy (`control_plane: gha`) |
| [roaming-nodes.md](roaming-nodes.md) | Non-Lima dynamic-IP roaming via Cloudflare Tunnel SSH |

## Concepts

| Document | Topics |
| --- | --- |
| [inventories.md](inventories.md) | `inventories/<slug>/`, groups, `control_plane`, `provider.platform: public` |
| [wireguard.md](wireguard.md) | Mesh model, hub build-up, post-build roaming dial, Mac / GHA |
| [lima.md](lima.md) | Lima guests, fingerprints, runtime home |
| [vault.md](vault.md) | Ansible Vault lifecycle, `.vault-pass` creation, WireGuard keys |
| [cluster.md](cluster.md) | gVisor, Docker Engine, Caddy, PowerDNS (always part of `task up`) |

## Reference

| Document | Topics |
| --- | --- |
| [tasks.md](tasks.md) | Public Task entrypoints + internal troubleshooting tasks |
| [scripts.md](scripts.md) | Python and shell helpers |
| [ansible.md](ansible.md) | Playbooks and roles |
| [repository-layout.md](repository-layout.md) | Directories and state files |
| [troubleshooting.md](troubleshooting.md) | Common failures |
| [docs-site.md](docs-site.md) | Starlight + Cloudflare Pages |

## Conventions

- **Worktree root** — directory containing `Taskfile.yml`, `inventories/`, and `internal/`.
- **`ENV`** — inventory slug (`dev`, `prod`, …).
- **`project`** — from `inventories/<provider>/hosts.yml` → `all.vars` (currently `example`).
- **`control_plane`** — `mac` (default; Mac controller peer + `task up`) or `gha` (Actions-only; no Mac peer).
- **`provider.platform: public`** — required; `vps` and `lima` are refused.
