# Networking

This is the networking contract for the Docker Swarm template. Both inventories
preserve the same management topology: one macOS controller
and three Ubuntu nodes connected by a project-owned WireGuard mesh.

| Inventory | Controller | Nodes | Interface | Public UDP |
|---|---:|---:|---|---:|
| templ-local | `10.79.0.1` | `10.79.0.11-13` | automatic macOS `utunN`; guest `wg0` | host forwards `51921-51923` to guest `51830` |
| templ-prod | `10.217.79.1` | `10.217.79.11-13` | automatic macOS `utunN`; server `scwg0` | `51830` |

## C4-style architecture views

The diagrams use C4 terminology, but stay focused on the network boundaries
that matter operationally. Boxes marked as containers are independently
running or deployed parts of the system named by `deployment_name` in
`deployment.yml`, not Docker containers.

### Level 1: system context

```text
+----------------------+
| Person               |
| Operator on the Mac  |
+----------+-----------+
           |
           | task commands and approved SSH
           v
+----------------------------------------------------------+
| Software system: <deployment_name>                       |
|                                                          |
| Project-owned controller, WireGuard management network,  |
| three Ubuntu manager/workers, Docker Swarm, and gVisor   |
+----------------------+------------------+----------------+
                       |                  |
           templ-local |                  | templ-prod
                       v                  v
            +------------------+   +------------------------+
            | Lima             |   | Hosting provider       |
            | Three VMs        |   | Three existing VPSes   |
            +------------------+   | Provider firewall      |
                       |            +------------------------+
                       |
                       | template-local backup target
                       v
            +------------------+
            | Garage           |
            | Lima default VM  |
            | Restic repo      |
            +------------------+

            templ-prod labeled backup manager -> external S3-compatible Restic repo
```

### Level 2: system containers

```text
+----------------------- macOS controller ------------------------+
|                                                                 |
|  +------------------+       +-------------------------------+   |
|  | Task + Ansible   |------>| Inventory, encrypted Vault,   |   |
|  | operator client  |       | known_hosts, rendered config  |   |
|  +--------+---------+       +-------------------------------+   |
|           |                                                     |
|           | owns launchd job and verifies runtime identity      |
|           v                                                     |
|  +----------------------------------------------------------+   |
|  | WireGuard container: automatic utunN                     |   |
|  | templ-local 10.79.0.1 or templ-prod 10.217.79.1       |   |
|  +----------+-------------------+-------------------+-------+   |
+-------------|-------------------|-------------------|-----------+
              | encrypted tunnel  | encrypted tunnel  | encrypted tunnel
              v                   v                   v
     +----------------+   +----------------+   +----------------+
     | Ubuntu node 1  |---| Ubuntu node 2  |---| Ubuntu node 3  |
     | WG + SSH       |   | WG + SSH       |   | WG + SSH       |
     | Docker manager |   | Docker manager |   | Docker manager |
     | gVisor workers |   | gVisor workers |   | gVisor workers |
     +--------+-------+   +--------+-------+   +--------+-------+
              \____________________|___________________/
                    full-mesh server-to-server WireGuard

Private mesh traffic:
  SSH TCP 22; Swarm manager TCP 2377; gossip TCP/UDP 7946;
  VXLAN data path UDP 4789. None is intended as a public service.
```

### Level 3: template-local deployment

```text
+------------------------------- macOS -------------------------------+
|                                                                     |
|  controller utunN                                                   |
|  10.79.0.1                                                          |
|       |                 |                   |                        |
|       | UDP 51921       | UDP 51922         | UDP 51923              |
|       v                 v                   v                        |
|  Lima dynamic       Lima dynamic        Lima dynamic                |
|  UDP forward        UDP forward         UDP forward                 |
+-------|-----------------|-------------------|------------------------+
        |                 |                   |
        v                 v                   v
  +-----------+     +-----------+       +-----------+
  | templ-local-1 |-----| templ-local-2 |-----| templ-local-3 |
  | wg0           |     | wg0           |     | wg0           |
  | 10.79.0.11    |-----| 10.79.0.12    |-----| 10.79.0.13    |
  | UDP 51830     |     | UDP 51830     |     | UDP 51830     |
  +-----------+     +-----------+       +-----------+
       \_____________________________________/
             encrypted full-mesh underlay

  Separate shared Lima default VM:
  +---------------------------------------------------------+
  | Garage container                                       |
  | macOS status/API: 127.0.0.1:3901                       |
  | labeled manager backup: host.lima.internal:3901         |
  | encrypted Restic repository; 30-day snapshot retention |
  +---------------------------------------------------------+
                                ^
                                |
              every six hours from run_on_backup=true node
```

Each project VM applies its tracked nftables input policy. The three different
macOS UDP ports are transport forwards only; stable management and Swarm
identity always uses `10.79.0.x` inside WireGuard.

### Level 3: template-production deployment

```text
                         public Internet
                                |
                 +--------------v---------------+
                 | Hosting-provider firewall    |
                 |                              |
                 | UDP 51830: exact controller  |
                 | and server public IPs only   |
                 | TCP 22: approved controller  |
                 | source for bootstrap/recovery|
                 | Swarm ports: never public    |
                 +---+-------------+------------+
                     |             |
       UDP 51830     |             | temporary TCP 22 bootstrap/recovery
                     |             |
 +-------------------+-------------+-----------------------------+
 | macOS controller                                                |
 | dynamic public IP -> utunN / 10.217.79.1                       |
 +----------+----------------------+----------------------+--------+
            | WireGuard            | WireGuard            | WireGuard
            v                      v                      v
   +----------------+     +----------------+     +----------------+
   | templ-prod-1   |-----| templ-prod-2   |-----| templ-prod-3   |
   | public endpoint|    | public endpoint|     | public endpoint|
   | scwg0          |----| scwg0          |-----| scwg0          |
   | 10.217.79.11   |    | 10.217.79.12   |     | 10.217.79.13   |
   | Swarm manager  |    | Swarm manager  |     | Swarm manager  |
   +----------------+     +----------------+     +----------------+
            \_____________________|____________________/
                    encrypted full-mesh underlay

   run_on_backup=true manager --HTTPS--> private S3-compatible bucket
                                      encrypted Restic Swarm-state repository
```

Normal SSH, Ansible, Swarm control, gossip, and VXLAN data traffic stays on
`10.217.79.x`. The public addresses are WireGuard endpoints; public TCP 22 is a
provider-firewall exception for bootstrap or recovery, not the steady-state
management path. The repository does not manage the hosting-provider firewall.

### Level 4: node network components

```text
                    encrypted WireGuard underlay
                               |
                               v
                  +--------------------------+
                  | wg0 (templ-local)       |
                  | or scwg0 (templ-prod)   |
                  +-----+--------------------+
                        |
             +----------+-----------+
             |                      |
             v                      v
      +-------------+       +-----------------------+
      | sshd        |       | Docker Engine         |
      | TCP 22      |       | Swarm manager/worker  |
      +-------------+       +---+-------------------+
                                |
                  +-------------+-------------+
                  | TCP 2377, TCP/UDP 7946,   |
                  | UDP 4789 on the mesh      |
                  +-------------+-------------+
                                |
                                v
                       +------------------+
                       | Swarm workload   |
                       | runsc / gVisor   |
                       | netstack network |
                       | default runtime  |
                       +------------------+
```

There is no public application edge in the current baseline. Publishing TCP
80/443 later requires a deliberate global edge service plus matching provider
and host policy; it does not happen as a side effect of `swarm-up`.

The project-owned Docker runtime configuration explicitly passes
`--network=sandbox` to `runsc`. This keeps TCP/IP processing in gVisor's
userspace netstack rather than selecting `--network=host`; `task verify`
requires the exact configuration before it runs its temporary gVisor workload.

All three managers are normally `Active`. The one inventory node marked
`swarm_run_on_backup: true` receives the Docker node label
`run_on_backup=true` and owns the server-side systemd backup timer. A backup
temporarily drains only that manager, waits for its Swarm tasks to stop, stops
only its Docker daemon to archive cold Swarm state, restarts the same manager,
and restores `Active` availability before uploading. Template-local uses
Garage's private Lima listener; template-production uses HTTPS to the configured
external S3-compatible service. Backup traffic is not a Swarm service and does
not publish a port.

## Swarm placement convention

`run_on_backup` is an explicit scheduling boundary, not an automatic
reservation. Every deployed service must use a strict placement constraint:

- Interruptible work deliberately assigned to the backup manager uses
  `node.labels.run_on_backup == true`.
- Ordinary work that must stay available while that manager is backed up uses
  `node.labels.run_on_backup != true`.

Placement preferences and unconstrained services do not satisfy this policy.
Standalone containers are forbidden on the backup manager because Swarm drain
cannot relocate or account for them. Work constrained only to
`run_on_backup=true` is intentionally unavailable during the short cold-backup
window. `swarm-up` reconciles one explicit `true` label and two explicit
`false` labels from inventory; `verify` uses the `true` constraint for its
temporary digest-pinned gVisor workload and removes it afterward.

The cold archive necessarily records the selected manager in its temporary
`Drain` state. After a disaster restore, rerun `swarm-up` before recovering
workloads so inventory restores all three managers to `Active` and reasserts
the node labels.

## Template-local path

The template-local configuration is rendered to
`.state/templ-local/wireguard/wg.conf`. Lima's dynamic UDP forwarder carries the
encrypted tunnel to each VM. SSH and Ansible then use the stable `10.79.0.x`
addresses.

Each VM runs a tracked nftables management policy. It accepts SSH from the
controller through `wg0`, permits established traffic, WireGuard bootstrap,
DHCP, and mesh ICMP, and rejects other inbound traffic. The policy does not
publish application ports.

Garage is separate from the three project VMs. Its container runs in the
existing shared Lima `default` profile and exposes its S3-compatible API on the
controller at `127.0.0.1:3901`. The labeled project VM reaches that forwarded
listener through Lima's private `host.lima.internal:3901` gateway.

## Template-production path

Public endpoints are used only to bootstrap or recover SSH and to carry
WireGuard UDP 51830. After the tunnel is healthy, Ansible and interactive SSH
use the private `10.217.79.x` addresses. The macOS controller configuration is
rendered beneath `.state/templ-prod/wireguard/` and restored at boot by the
project launchd service.

The provider firewall remains operator-owned. Permit UDP 51830 only between
the controller and the three exact servers, and temporarily permit TCP 22 from
the controller's trusted `/32` during initial bootstrap or recovery. Remove
the public TCP 22 rule only after all three `wg-ssh` checks succeed.

The labeled template-production manager makes outbound HTTPS requests directly
to the selected S3-compatible endpoint. No inbound provider-firewall rule,
Swarm service, or public storage listener is required.

`task wg-remove PROVIDER=templ-prod` is a controller-only disconnect. It unloads the
project launchd job and stops the verified macOS `utunN`, while preserving its
configuration and leaving every server tunnel and server-side resource
untouched. `task wg-up PROVIDER=templ-prod` reuses the verified alias file and
reconnects through the server tunnels without requiring public SSH.
