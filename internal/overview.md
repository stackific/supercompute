# Overview

Supercompute is a purpose-built cloud for AI-first workloads that you can self-host on commodity hardware—including a VM on your laptop. High availability is achievable with as few as two nodes. It is developed by [Stackific Inc.](https://stackific.com/).

This worktree automates **provider infrastructure**: WireGuard meshes, optional Lima roaming guests on macOS, Ansible Vault, and an optional **cluster stack** (gVisor, Docker Engine, GeoDNS PowerDNS with MaxMind geoipupdate) on deployment nodes.

## What this automation does

| Layer | Responsibility |
| --- | --- |
| **Inventory** | Declares hosts, mesh IPs, endpoints, fingerprints, roaming flags |
| **WireGuard** | macOS controller + Ubuntu nodes on `scwg0` (UDP 51830) |
| **Bootstrap SSH** | Public endpoint, Lima-local SSH, or Cloudflare Tunnel (non-Lima roaming) |
| **Vault** | Encrypted secrets per provider; WireGuard key material |
| **Lima** | Factory for `node_lima_guest` Ubuntu guests on Apple Silicon |
| **Cluster** | Optional runtime and GeoDNS on `deployment` group hosts |

The project does **not** provision VPS instances, Cloudflare tunnels, or parent-zone DNS records. Operators create those outside this repo and fill inventory.

## Controller and nodes

- **Controller** — macOS on Apple Silicon. Runs WireGuard (`wg-quick`), Task entrypoints, Lima (for dev guests), and Ansible from the Mac.
- **Static public hosts** — Ubuntu 26.04 `x86_64` VMs with stable public IPs (`static-1`, …). Act as mesh **hubs** when roaming nodes exist.
- **Roaming hosts** — `wireguard_roaming: true`. Initiate WireGuard to the hub; no inbound UDP 51830 on home routers.
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

**Development (`dev`)** — one public static hub + one Lima roaming guest, mesh `10.217.80.0/24`. See [setup-dev.md](setup-dev.md).

**Production (`prod`)** — operator-defined mesh (often `10.217.79.0/24`), gitignored inventory restored from backup. See [setup-prod.md](setup-prod.md).

**Home lab roaming (prod)** — dynamic IP Ubuntu VM joined via Cloudflare Tunnel SSH bootstrap. See [roaming-nodes.md](roaming-nodes.md).

## External dependencies

Operators supply:

- At least one **public IP** for the static hub (UDP 51830 open for roaming egress).
- **External Postgres** for application data (not installed by this automation).
- **MaxMind** credentials in vault (optional) for continent GeoDNS; PowerDNS still runs without them.
- **Cloudflare** account and tunnel for non-Lima roaming bootstrap.

## Related docs

- [get-started.md](get-started.md) — minimal command sequence
- [wireguard.md](wireguard.md) — hub routing and roaming rules
- [tasks.md](tasks.md) — full Taskfile reference
