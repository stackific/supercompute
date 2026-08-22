# Internal operator documentation

Markdown runbooks and reference at the **worktree root** (`internal/`). The public Starlight site lives in `docs/` — see [docs-site.md](docs-site.md).

## Start here

| Document | Purpose |
| --- | --- |
| [overview.md](overview.md) | What Supercompute is and how the automation fits together |
| [get-started.md](get-started.md) | Fast path from clone to a working `dev` mesh |
| [prerequisites.md](prerequisites.md) | Host tools, `deployment_name`, SSH identity |

## Runbooks

| Document | Audience |
| --- | --- |
| [setup-dev.md](setup-dev.md) | `PROVIDER=dev` — public hub + Lima `node_lima_guest` roaming |
| [setup-prod.md](setup-prod.md) | Operator `prod` mesh (restore `inventories/prod/` from backup; gitignored) |
| [roaming-nodes.md](roaming-nodes.md) | Non-Lima dynamic-IP roaming via Cloudflare Tunnel SSH |

## Concepts

| Document | Topics |
| --- | --- |
| [inventories.md](inventories.md) | `inventories/<slug>/`, groups, `provider.platform: public` |
| [wireguard.md](wireguard.md) | Mesh model, static hub, roaming, Mac controller |
| [lima.md](lima.md) | Lima guests, fingerprints, runtime home |
| [vault.md](vault.md) | Ansible Vault lifecycle and WireGuard keys |
| [cluster.md](cluster.md) | gVisor, Docker Engine, GeoDNS PowerDNS |

## Reference

| Document | Topics |
| --- | --- |
| [tasks.md](tasks.md) | Taskfile entrypoints |
| [scripts.md](scripts.md) | Python and shell helpers |
| [ansible.md](ansible.md) | Playbooks and roles |
| [repository-layout.md](repository-layout.md) | Directories and state files |
| [troubleshooting.md](troubleshooting.md) | Common failures |
| [docs-site.md](docs-site.md) | Starlight + Cloudflare Pages |

## Conventions

- **Worktree root** — directory containing `Taskfile.yml`, `deployment.yml`, `inventories/`, and `internal/`.
- **`PROVIDER`** — inventory slug (`dev`, `prod`, …).
- **`deployment_name`** — from `deployment.yml` (currently `sc`).
- **`provider.platform: public`** — required; `vps` and `lima` are refused.
