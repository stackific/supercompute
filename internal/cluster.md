# Cluster stack

`task up` brings up the WireGuard mesh and installs runtime/DNS software on every host in the **`nodes`** group.

## Software installed (`cluster_node` role, `present`)

| Component | Packages / services |
| --- | --- |
| **gVisor** | `runsc` from gvisor.dev apt repo |
| **Docker Engine** | `docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-buildx-plugin` from Docker’s Ubuntu repo |
| **PowerDNS** | `pdns-server`, `dnsutils` |
| **Caddy** | Reverse proxy: `sc-app.` → `sc` container, `sc-api.` → `supercompute` container |
| **sc** | `ghcr.io/stackific/sc/sc:latest`, restart `unless-stopped`; `SC_API` = `https://` + `dns_prefix_api` + `hostname` |
| **supercompute** | `ghcr.io/stackific/sc/supercompute:latest`, restart `unless-stopped`; `SC_DASH` = `https://` + `dns_prefix_app` + `hostname` |

## DNS boundary

PowerDNS listens on the node mesh address only (`pdns.d/supercompute-local.conf`) so host DNS stays on `systemd-resolved`. Teardown removes that drop-in and restarts `systemd-resolved`.

Set `hostname` in `hosts.yml` → `all.vars` (for example `example.com`). Prefixes come from `group_vars/all/main.yml` (`dns_prefix_ns`, `dns_prefix_api`, `dns_prefix_app`, `dns_prefix_apps`; defaults `ns`, `sc-api`, `sc-app`, `apps`). Parent DNS: A for `ns.`, CNAME `sc-api.` and `sc-app.` to the nameserver hostname, and NS-delegate `apps.` to it. If the DNS is hosted on Cloudflare, do not enable the proxy orange icons. PowerDNS currently listens on the mesh address only.

## Architecture mapping

Deb architecture follows the host:

- `x86_64` → `amd64` packages
- `aarch64` Lima guests → arm64 packages where applicable

## Tasks

```sh
task up ENV=<env>
task down ENV=<env> CONFIRM=down-<slug>   # stop; keeps vault, .state/, Lima
```

`down` removes cluster software and configs, tears down node WireGuard (including `/etc/supercompute/*`), and disconnects the Mac controller mesh (`control_plane: mac`). Down playbooks use mesh SSH when available and bootstrap recovery (public IP, Lima-local, Cloudflare) when the mesh is down.

Factory-reset local automation (vault, `.state/`, optional Lima) with `env-reset` / `dev-reset` / `dev-reset-lima` — see [tasks.md](tasks.md). For GHA-managed inventories use the Actions workflow instead — [gha-deploy.md](gha-deploy.md).

## Prerequisites

1. Working inventory and Lima guests (when used).
2. Any required external DNS delegation and firewall rules, managed outside this role.

## Related

- [setup-prod.md](setup-prod.md) — production firewall guidance
- [ansible.md](ansible.md) — `cluster_node` role
