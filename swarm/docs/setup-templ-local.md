# Template-local setup

The `templ-local` inventory is the Docker Swarm template's development profile. It
manages three Ubuntu 26.04 ARM64 Lima VMs, their
WireGuard mesh, and an independent Garage S3-compatible service.

## Prerequisites

- macOS on Apple Silicon
- Lima `2.2.0`
- Task, `uv`, and WireGuard tools
- Docker CLI
- an existing shared Lima `default` profile with Docker and a `user-v2`
  network attachment

This repository never creates, changes, or deletes the shared `default` Lima
profile. Verify the host dependencies before creating project state:

```bash
for tool in task uv limactl wg wg-quick docker ssh; do
  command -v "$tool" >/dev/null || exit 1
done

limactl --version
env -u LIMA_HOME limactl list
DOCKER_HOST="unix://$HOME/.lima/default/sock/docker.sock" docker info
```

## Start from a new checkout

Before the first command, set `deployment_name` in `deployment.yml` to the
customer's stable deployment name. See [the deployment-name
contract](../README.md#customer-deployment-name). The committed value is defined
only in `deployment.yml`. Set `encryption_at_rest: true` before the first
`swarm-up` to require encrypted business-data storage under `/srv/secure`; see
[encrypted business-data storage](encrypted-at-rest.md).

```bash
task setup
task vault-init PROVIDER=templ-local
task lima-up PROVIDER=templ-local
task wg-up PROVIDER=templ-local
task garage-up
```

Verify and use the mesh:

```bash
task lima-status PROVIDER=templ-local
task wg-status PROVIDER=templ-local
task wg-verify-after PROVIDER=templ-local
task wg-ssh PROVIDER=templ-local NODE=templ-local-1
```

The controller configuration is `.state/templ-local/wireguard/wg.conf`; guest interfaces
are named `wg0`. The three Lima VMs forward WireGuard through host UDP ports
51921-51923. `lima-up` refuses a conflicting port.

The Lima lifecycle tasks use `$HOME/.lima/.templ-local` as their real,
persistent `LIMA_HOME`. This provider-scoped directory is deliberately hidden
from ordinary default-home `limactl list` discovery and keeps Lima's socket
paths below macOS's 104-byte limit. It is separate from the shared
`$HOME/.lima/default` instance and survives restarts.

Standalone Garage uses the fixed Docker names `swarm-garage`,
`swarm-garage-data`, and `swarm-garage-metadata` in that shared `default`
profile. Its lifecycle does not vary with `PROVIDER`. Confirmed
`garage-destroy` also recognizes and removes older deployment-prefixed Garage
resources only when their Stackific ownership labels match their names.

### Restarting locked-down Lima guests

Template-local restart has a deliberate boot-only exception to break Lima's startup
dependency: for at most 600 seconds, the guest delays the project nftables
lockdown while Lima establishes its host-only SSH management connection and
dynamic UDP forward. This path exists only on Lima's private `user-v2` network;
the configured macOS SSH ports are not published on a LAN or public address.
The gate identifies the one WireGuard peer whose allowed address is the
controller's exact `/32`, requires a recent handshake from that public key,
and then applies the tracked lockdown. On timeout or helper failure it applies
the same policy fail-closed.

The final policy permits an already-established Lima bootstrap connection to
finish but drops every new non-WireGuard TCP/22 connection. `lima-up` therefore
checks an existing VM from the controller side and waits for its UDP forward;
Ubuntu and architecture checks run afterward through WireGuard in `wg-up` and
`verify`. When `.state/templ-local/wireguard/wg.conf` already exists, `wg-up` waits for the
UDP forwards, restores the controller interface if necessary, and retries all
three WireGuard SSH paths. If any path remains unavailable, it stops instead
of falling back to ordinary Lima SSH. Ordinary Lima bootstrap is reserved for
a first installation with no controller WireGuard configuration; that path
waits for the UDP forwards only after WireGuard is listening in each guest.

Install this startup gate once while the existing VMs and WireGuard paths are
healthy by rerunning:

```bash
task wg-up PROVIDER=templ-local
```

After that update, the normal restart sequence is `task lima-up
PROVIDER=templ-local` followed by
`task wg-up PROVIDER=templ-local` if the controller interface was not already
running. The timeout does not require public or ordinary SSH afterward: once
Lima has established the UDP forward, the fail-closed policy still permits the
controller to establish WireGuard later. If a VM is already trapped behind the
old firewall unit, the new role cannot safely bypass it: disable
`manual-wg-firewall.service` from the Lima serial console, then rerun those two
tasks. Alternatively, after accepting the loss of the disposable VM disks and
their local Swarm state, run `task lima-destroy PROVIDER=templ-local
CONFIRM=destroy-templ-local`, `task lima-up PROVIDER=templ-local`, and `task
wg-up PROVIDER=templ-local`. `wg-up` proves all three recreated
guests accept ordinary Lima access before reusing the existing Vault and
controller configuration to bootstrap them. It clears only the stale local
WireGuard `known_hosts` cache so the recreated guests' new SSH host keys can be
recorded; it never uses that fallback for legacy locked guests. Automation does
not destroy VMs as a repair step.

## Baseline Docker Swarm

After WireGuard is healthy, create the baseline three-manager Swarm:

```bash
task swarm-up PROVIDER=templ-local
task swarm-status PROVIDER=templ-local
task verify PROVIDER=templ-local
```

`swarm-up` installs SHA256-pinned Docker Engine `29.7.2`, Docker CLI `29.7.2`,
and containerd `2.3.3` ARM64 packages from Docker's Ubuntu 26.04 repository. It
also installs the complete SHA512-pinned gVisor `20260810.0` ARM64 bundle and
configures Docker to use `runsc` with gVisor netstack by default.
When `encryption_at_rest: true`, it first provisions and unlocks the fscrypt v2
business-data root described in [encrypted business-data storage](encrypted-at-rest.md).
All three managers are schedulable with `swarm_availability: active`. Exactly one inventory
node must have `swarm_run_on_backup: true`; `swarm-up` renders that selection as
the Docker node label `run_on_backup=true` and explicitly labels the other two
`run_on_backup=false`. Manager and data-path traffic uses only their
`10.79.0.x` WireGuard addresses. The project WireGuard firewall permits the
required Swarm ports only between those mesh peers.

`verify` checks the pinned Ubuntu, Docker, gVisor, WireGuard, firewall, and
three-manager Swarm baseline. It runs a digest-pinned temporary gVisor job with
the strict `node.labels.run_on_backup==true` constraint, proves the job ran on
the selected manager under `runsc`, and removes the service even when
verification fails. The image may remain in Docker's local cache.

Node scheduling and backup ownership are declared in
`inventories/templ-local/hosts.yml`. To move backup ownership, change the old node to
`swarm_run_on_backup: false`, change the replacement to `true`, and rerun
`task swarm-up PROVIDER=templ-local`. Zero or multiple `true` values, any manager not
set to `active`, or an unrecognized value is rejected.

The label is a placement selector, not a reservation. Every future Swarm
service must declare one of these strict constraints:

- Backup-node-specific, interruptible service:
  `node.labels.run_on_backup == true`
- Ordinary service that must stay off the backup node:
  `node.labels.run_on_backup != true`

Do not use a placement preference or omit the constraint: either choice allows
ordinary work to reach the backup manager. Do not run standalone containers on
that manager. Services pinned only to the backup manager must tolerate a short
interruption during each cold backup.

## Scheduled cold Swarm-state backups

Start Garage before `swarm-up`. The labeled manager reaches Garage through
Lima's private `host.lima.internal` gateway rather than a public listener.
`swarm-up` then initializes or verifies an encrypted Restic repository under
`<deployment_name>/<inventory_slug>/swarm-state/v1`, installs SHA256-pinned Restic
`0.19.1` for ARM64, and enables `<deployment_name>-backup.timer` only on the
manager labeled `run_on_backup=true`.

Every six hours, that manager verifies the exact healthy three-manager quorum,
its own WireGuard Swarm address, `Active` availability, unique label ownership,
and the absence of standalone containers. It temporarily changes only that
manager to `Drain`, waits for its Swarm tasks to stop, stops only its Docker
daemon, and archives only `/var/lib/docker/swarm`. It restarts Docker and
returns the same manager to `Active` in the cleanup path without leaving or
rejoining the Swarm. Only after the three-manager quorum, active availability,
and label are restored does it upload the encrypted Restic snapshot to Garage
and prune snapshots outside the 30-day window.

Use `task swarm-status PROVIDER=templ-local` to see the timer and last service result.
`task verify PROVIDER=templ-local` additionally checks that only the labeled manager
owns an enabled six-hour timer, the exact 30-day configuration, the pinned
Restic binary, and a readable encrypted repository. It does not force an
unscheduled cold backup.

This backup contains Swarm Raft state, membership, services, configs, secrets,
and Swarm encryption material. It does not contain application volumes,
database data, container images, the Lima VMs, the Garage data itself, or the
Vault. Back those up separately. Preserve the local encrypted Vault and its
matching `.vault-pass`; losing the Restic password makes the repository
unrecoverable, while losing a node's `vault_encryption_at_rest_passphrases`
entry makes that node's fscrypt data unrecoverable after the key leaves memory.

To make all three nodes leave the Swarm, remove the baseline gVisor runtime,
and return Docker to `runc` without uninstalling Docker or changing WireGuard,
run:

```bash
task swarm-down PROVIDER=templ-local
```

This stops Swarm orchestration and any workloads deployed through it. It also
removes the local backup service and timer, but preserves all Garage objects.

## Replace the project VMs

For a controlled replacement of one cluster member, use the [node lifecycle
runbook](node-lifecycle.md). The commands below replace all three project VMs;
they are not a single-node removal procedure.

For an immutable image update, remove the mesh before deleting the VMs:

```bash
task wg-remove PROVIDER=templ-local
task lima-destroy PROVIDER=templ-local CONFIRM=destroy-templ-local
task lima-up PROVIDER=templ-local
task wg-up PROVIDER=templ-local
```

If `wg-up` has never created `.state/templ-local/wireguard/wg.conf`, omit `wg-remove`.
This path preserves the Vault, Garage data, tool caches, and shared Lima
`default` profile.

## Operate Garage

```bash
task garage-status
task garage-credentials
task garage-down
task garage-up
```

`garage-down` preserves the named metadata and data volumes. Permanent deletion
is separately confirmation-gated:

```bash
task garage-destroy CONFIRM=destroy-garage-data
```

## Release or reset template-local resources

`task wg-remove PROVIDER=templ-local` removes only the project WireGuard interfaces
and generated tunnel state. To delete every project-owned template-local artifact:

```bash
task reset PROVIDER=templ-local CONFIRM=reset-templ-local
```

Reset deletes the three project VMs, managed Garage objects and volumes, local
Vault, state, virtual environment, and caches. It does not delete or reconfigure
the shared Lima `default` VM or Lima's global `~/.lima` directory. It also
deletes the local per-node fscrypt passphrases and the VM disks containing
`/srv/secure`; this is intentional data destruction, not an encryption-disable
operation.
