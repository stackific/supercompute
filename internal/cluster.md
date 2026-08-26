# Cluster stack

`task up` brings up the WireGuard mesh and installs runtime/DNS software on every host in the **`deployment`** group.

## Software installed (`cluster_node` role, `present`)

| Component | Packages / services |
| --- | --- |
| **gVisor** | `runsc` from gvisor.dev apt repo |
| **Docker Engine** | `docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-buildx-plugin` from Docker’s Ubuntu repo |
| **PowerDNS** | `pdns-server`, `dnsutils` |
| **Caddy** | `caddy` package only; its systemd service remains disabled and stopped |

## DNS boundary

`cluster_node` installs and starts PowerDNS but deliberately does not create DNS
zones, configure an application hostname, or perform DNS lookups. DNS
delegation remains an external operator responsibility.

Set the externally managed nameserver hostname in `config.yml` with
`nameserver_hostname`; its default is `ns.example.com`.

## Architecture mapping

Deb architecture follows the host:

- `x86_64` → `amd64` packages
- `aarch64` Lima guests → arm64 packages where applicable

## Tasks

```sh
task up PROVIDER=<slug>
task down PROVIDER=<slug> CONFIRM=down-<slug>
```

`down` removes cluster software, tears down node WireGuard, and disconnects the Mac controller mesh.

## Prerequisites

1. Working inventory and Lima guests (when used).
2. Any required external DNS delegation and firewall rules, managed outside this role.

## Related

- [setup-prod.md](setup-prod.md) — production firewall guidance
- [ansible.md](ansible.md) — `cluster_node` role
