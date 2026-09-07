# Overview

Supercompute is a purpose-built cloud for AI-first workloads that you can self-host on commodity hardware—including a VM on your laptop. High availability is achievable with as few as two nodes. It is developed by Stackific Inc.

This worktree automates **provider infrastructure**: WireGuard meshes, optional Lima roaming guests on macOS, Ansible Vault, and a **cluster stack** (gVisor, Docker Engine, Caddy, and PowerDNS) on deployment nodes. `task up` (and the GHA `up` action) always bring up the mesh **and** the cluster stack together.

## What this automation does

| Layer | Responsibility |
| --- | --- |
| **Inventory** | Declares hosts, mesh IPs, endpoints, fingerprints, roaming flags, `control_plane` |
| **WireGuard** | Mac controller and/or Ubuntu nodes on `scwg0` (UDP 51830); post-build roaming dial |
| **Bootstrap SSH** | Public endpoint, Lima-local SSH, or Cloudflare Tunnel (non-Lima roaming) |
| **Vault** | Encrypted secrets per provider; WireGuard key material |
| **Lima** | Factory for `node_lima_guest` Ubuntu guests on Apple Silicon |
| **Cluster** | Runtime software on `deployment` group hosts (part of every `up`) |
| **GHA (optional)** | Manual Actions deploy for `control_plane: gha` inventories |

The project does **not** provision VPS instances, Cloudflare tunnels, or parent-zone DNS records. Operators create those outside this repo and fill inventory.

## Controller and nodes

- **Mac control plane (`control_plane: mac`)** — macOS on Apple Silicon. Runs WireGuard (`wg-quick`), Task entrypoints, Lima (for dev guests), and Ansible from the Mac. Mesh peer at `node_controller_address` (usually `.1`).
- **GHA control plane (`control_plane: gha`)** — GitHub-hosted runner mutates the mesh; **no** Mac peer. See [gha-deploy.md](gha-deploy.md).
- **Static public hosts** — Ubuntu 26.04 `x86_64` VMs with stable public IPs (`static-1`, …). Build-up hub is the first static; day-2 roaming may dial any public static when forwarding is enabled on all of them.
- **Roaming hosts** — `roaming: true`. Initiate WireGuard to a public static; no inbound UDP 51830 on home routers.
- **Lima guests** — `node_lima_guest: true`, `aarch64`. Roaming peers created on the Mac; bootstrap SSH is Lima-local, not Cloudflare.

## Platform dispatch

Every inventory must set:

```yaml
provider:
  platform: public
  mode: remote
```

Legacy `provider.platform: vps` and `provider.platform: lima` are **refused** at task dispatch. Lima is only a guest factory under `public` meshes.

## Typical flows

**Development (`dev`)** — one public static hub + one Lima roaming guest, mesh `10.217.80.0/24`, `control_plane: mac`. See [setup-dev.md](setup-dev.md).

**Production (`prod`)** — two static public nodes (`10.217.79.0/24`), committed inventory; Mac or GHA control plane. See [setup-prod.md](setup-prod.md) and [gha-deploy.md](gha-deploy.md).

**Home lab roaming (prod)** — dynamic IP Ubuntu VM joined via Cloudflare Tunnel SSH bootstrap. See [roaming-nodes.md](roaming-nodes.md).

## External dependencies

Operators supply:

- At least one **public IP** for a static hub (UDP 51830 open for roaming egress on every dialable static).
- **Postgres database with owner role** hosted outside of the Supercompute cloud (not installed by this automation).
- **Cloudflare** account and tunnel for non-Lima roaming bootstrap (operator-owned; outside Ansible).

## Related docs

- [get-started.md](get-started.md) — minimal command sequence
- [wireguard.md](wireguard.md) — hub routing, roaming dial, control planes
- [tasks.md](tasks.md) — full Taskfile reference
