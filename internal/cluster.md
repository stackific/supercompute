# Cluster stack

`task up` brings up the WireGuard mesh and installs runtime/DNS software on every host in the **`deployment`** group.

## Software installed (`cluster_node` role, `present`)

| Component | Packages / services |
| --- | --- |
| **gVisor** | `runsc` from gvisor.dev apt repo |
| **Docker Engine** | `docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-buildx-plugin` from Docker’s Ubuntu repo |
| **PowerDNS** | `pdns-server`, `pdns-backend-geoip` |
| **GeoIP** (optional) | `geoipupdate`, MaxMind `GeoLite2-Country`, systemd timer — only when vault has both `maxmind_account_id` and `maxmind_license_key` |

Caddy was removed from the active install path; `down` still cleans legacy Caddy files if present.

## GeoDNS defaults

From `roles/cluster_node/defaults/main.yml`:

| Setting | Default |
| --- | --- |
| Public zone apex | `test-app.stackific.com` |
| NS hostname | `ns1.stackific.com` (parent zone on `stackific.com`, **DNS-only / grey cloud**) |
| Static hub host | `static-1` |
| PowerDNS listen | Mesh IP + static public IP when `prod_wireguard_endpoint` is set |

PowerDNS serves on the mesh for internal use and on the static VPS public IP so Cloudflare NS delegation can reach authoritative DNS.

**HTTP is not served by this role** — mesh-only application binding is an operator concern. Parent zone must delegate with **NS records**, not orange-cloud CNAME chains that break GeoDNS.

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
2. Vault secrets for MaxMind only when continent GeoDNS is required (both `maxmind_account_id` and `maxmind_license_key` in `deployment_vault.secrets`).
3. Parent-zone DNS: NS for delegated zone → `ns1.stackific.com`; A records for `ns1` at parent (DNS-only).
4. Firewall: UDP/TCP **53** on the static hub public IP if external DNS resolution is required.

## Verification hints

From a mesh-connected host or Mac:

```sh
task ssh PROVIDER=dev NODE=static-1
dig @10.217.80.11 test-app.stackific.com   # example mesh IP
```

Exact addresses depend on inventory.

## Related

- [setup-prod.md](setup-prod.md) — production DNS and firewall sections
- [vault.md](vault.md) — MaxMind credentials
- [ansible.md](ansible.md) — `cluster_node` role
