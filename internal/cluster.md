# Cluster stack

`task up` brings up the WireGuard mesh and installs runtime/DNS software on every host in the **`nodes`** group.

## Software installed (`cluster_node` role, `present`)

| Component | Packages / services |
| --- | --- |
| **gVisor** | `runsc` from gvisor.dev apt repo |
| **Docker Engine** | `docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-buildx-plugin` from Docker’s Ubuntu repo |
| **PowerDNS** | `pdns-server`, `dnsutils` |
| **Caddy** | Reverse proxy: `sc_app` → `sc` container, `sc_api` → `supercompute` container |
| **sc** | `ghcr.io/stackific/sc/sc:latest`, restart `unless-stopped` |
| **supercompute** | `ghcr.io/stackific/sc/supercompute:latest`, restart `unless-stopped` |

Container env vars are a curated pass-through of `hosts.yml` `all.vars` (not every inventory key). `/etc/supercompute/hosts.yml` on the node is a separate file; it is not mounted into the containers.

| Container | Env | Value |
| --- | --- | --- |
| `sc` | `SC_API` | `https://` + `sc_api` |
| `supercompute` | `SC_APP` | `https://` + `sc_app` |
| `supercompute` | `SC_NS` | `sc_ns` (FQDN, no scheme) |
| `supercompute` | `SC_APPS` | `sc_apps` (FQDN, no scheme) |

## DNS boundary

PowerDNS listens on the node mesh address only (`pdns.d/supercompute-local.conf`) so host DNS stays on `systemd-resolved`. Teardown removes that drop-in and restarts `systemd-resolved`.

Set `sc_ns`, `sc_api`, `sc_app`, and `sc_apps` in `hosts.yml` → `all.vars`. `sc_ns` must have a parent zone (for example `ns.example.com`) so Mac LaunchDaemon reverse-DNS can be derived from it (`ns.example.com` → `com.example`). Parent DNS: A for `sc_ns`, CNAME `sc_api` and `sc_app` to `sc_ns`, and NS-delegate `sc_apps` to `sc_ns`. If the DNS is hosted on Cloudflare, do not enable the proxy orange icons. PowerDNS currently listens on the mesh address only.

## Architecture mapping

Deb architecture follows the host:

- `x86_64` → `amd64` packages
- `aarch64` Lima guests → arm64 packages where applicable

## Tasks

```sh
task up ENV=<env>
task down ENV=<env> CONFIRM=down-<slug>   # stop; keeps vault, .state/, Lima
```

`down` removes cluster software and configs, tears down node WireGuard (including `/etc/supercompute/*`), and disconnects the Mac controller mesh (`control_plane: mac`). Down playbooks use mesh SSH when available and bootstrap recovery (public IP, Lima-local, rathole jump) when the mesh is down. Rathole itself stays installed so roaming recovery still works.

Factory-reset local automation (vault, `.state/`, optional Lima) with `env-reset` / `dev-reset` / `dev-reset-lima` — see [tasks.md](tasks.md). For GHA-managed inventories use the Actions workflow instead — [gha-deploy.md](gha-deploy.md).

## Prerequisites

1. Working inventory and Lima guests (when used).
2. Any required external DNS delegation and firewall rules, managed outside this role.

## Related

- [setup-prod.md](setup-prod.md) — production firewall guidance
- [ansible.md](ansible.md) — `cluster_node` role
