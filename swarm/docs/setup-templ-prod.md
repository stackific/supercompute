# Template-production setup

The `templ-prod` inventory is the Docker Swarm template's production profile.
It manages a WireGuard mesh between one macOS controller and three existing
Ubuntu 26.04 AMD64 servers.

| Node | WireGuard address |
|---|---:|
| `templ-prod-1` | `10.217.79.11` |
| `templ-prod-2` | `10.217.79.12` |
| `templ-prod-3` | `10.217.79.13` |

The project does not create servers or provider firewall rules.

## Prepare the controller

Install Git, Task, `uv`, and WireGuard tools on macOS, clone the repository,
enter this project directory, and sync the locked controller:

Before the first command, set `deployment_name` in `deployment.yml` to the
customer's stable deployment name. See [the deployment-name
contract](../README.md#customer-deployment-name). The committed value is defined
only in `deployment.yml`. Set `encryption_at_rest: true` before the first
`swarm-up` to require encrypted business-data storage under `/srv/secure`; see
[encrypted business-data storage](encrypted-at-rest.md).

```bash
brew install git go-task/tap/go-task uv wireguard-tools
task setup
```

Create and load one dedicated SSH identity:

```bash
ssh-keygen -t ed25519 -a 100 -f ~/.ssh/swarm-templ-prod -C "docker-swarm templ-prod"
ssh-add ~/.ssh/swarm-templ-prod
```

Back up both key files securely.

## Prepare the servers

Create three servers named `templ-prod-1`, `templ-prod-2`, and `templ-prod-3` using the
provider's official Ubuntu Server 26.04 AMD64 image. In each provider console,
create the expected `ops` account, install the dedicated public key, and grant
the documented passwordless sudo contract:

```bash
sudo adduser --disabled-password --gecos '' ops
sudo install -d -o ops -g ops -m 0700 /home/ops/.ssh
sudo tee /home/ops/.ssh/authorized_keys >/dev/null
```

Paste the public key, press Control+D, then run:

```bash
sudo chown ops:ops /home/ops/.ssh/authorized_keys
sudo chmod 600 /home/ops/.ssh/authorized_keys
printf '%s\n' 'ops ALL=(ALL) NOPASSWD:ALL' | \
  sudo tee /etc/sudoers.d/90-docker-swarm-ops >/dev/null
sudo chmod 440 /etc/sudoers.d/90-docker-swarm-ops
sudo visudo -cf /etc/sudoers.d/90-docker-swarm-ops
sudo -u ops sudo -n true
```

Verify each installed operator key against the controller and record the
server's complete ED25519 host-key fingerprint from its trusted console:

```bash
sudo ssh-keygen -lf /home/ops/.ssh/authorized_keys
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub | awk '{print $2}'
```

## Add the server IPs and host-key fingerprints

Before running `vault-init` or `wg-up`, edit `inventories/templ-prod/hosts.yml`. For
each of `templ-prod-1`, `templ-prod-2`, and `templ-prod-3`, set both:

- `prod_wireguard_endpoint` to that server's public IPv4 address or DNS
  name.
- `prod_ssh_host_ed25519_sha256` to the complete `SHA256:...` fingerprint
  printed by the trusted-console command above for
  `/etc/ssh/ssh_host_ed25519_key.pub`.

For example, replace the values for all three hosts using this shape:

```yaml
templ-prod-1:
  prod_wireguard_endpoint: "203.0.113.11"
  prod_ssh_host_ed25519_sha256: "SHA256:REPLACE_WITH_COMPLETE_FINGERPRINT"
templ-prod-2:
  prod_wireguard_endpoint: "203.0.113.12"
  prod_ssh_host_ed25519_sha256: "SHA256:REPLACE_WITH_COMPLETE_FINGERPRINT"
templ-prod-3:
  prod_wireguard_endpoint: "203.0.113.13"
  prod_ssh_host_ed25519_sha256: "SHA256:REPLACE_WITH_COMPLETE_FINGERPRINT"
```

Use the public server addresses here, not the `10.217.79.x` WireGuard
addresses. The fingerprint is the server's SSH host-key fingerprint, not the
operator key fingerprint from `authorized_keys`.

## Provider firewall

Allow inbound UDP 51830 only from the controller's public `/32` and the three
server public `/32` addresses. During initial bootstrap or recovery, also allow
inbound TCP 22 from the controller's `/32`. Leave all other unsolicited inbound
traffic denied. Confirm the provider firewall is stateful before relying on
this policy.

## Initialize and deploy

```bash
task vault-init PROVIDER=templ-prod
task wg-up PROVIDER=templ-prod
```

`vault-init` creates the encrypted WireGuard key maps and ignored password
file. Back up both `inventories/templ-prod/group_vars/all/vault.yml` and
`inventories/templ-prod/.vault-pass` securely.

`wg-up` verifies all three host fingerprints before mutation, installs the
macOS launchd tunnel, reconciles each server serially, and proves controller-to-
server and server-to-server mesh SSH. It uses public SSH only when the complete
private mesh is not already reachable.

Verify every path:

```bash
task wg-status PROVIDER=templ-prod
task wg-ssh PROVIDER=templ-prod NODE=templ-prod-1
task wg-ssh PROVIDER=templ-prod NODE=templ-prod-2
task wg-ssh PROVIDER=templ-prod NODE=templ-prod-3
```

After all three SSH checks succeed, remove the temporary public TCP 22 rule.
For recovery, use the provider console or temporarily restore TCP 22 from the
controller's trusted `/32`, rerun `wg-up`, verify the mesh, and remove the rule
again.

## Resume from a fresh computer

Keep these items backed up together before the original controller is lost:

- The current repository, including `inventories/templ-prod/hosts.yml` with the
  public endpoints, SSH host-key fingerprints, `swarm_availability`, and the
  single `swarm_run_on_backup: true` selection.
- `~/.ssh/swarm-templ-prod` and `~/.ssh/swarm-templ-prod.pub`.
- `inventories/templ-prod/group_vars/all/vault.yml` and
  `inventories/templ-prod/.vault-pass`; these include the per-node fscrypt unlock
  passphrases when `encryption_at_rest: true`.
- `.state/templ-prod/known_hosts`. This is trusted public-key state rather than a
  secret, but it is required to reconnect without scanning public TCP 22.

On the fresh Mac, clone or restore the repository, restore those files at the
same paths, and enforce their permissions:

```bash
mkdir -p ~/.ssh .state/templ-prod inventories/templ-prod/group_vars/all
chmod 700 ~/.ssh .state/templ-prod
chmod 600 ~/.ssh/swarm-templ-prod
chmod 644 ~/.ssh/swarm-templ-prod.pub
chmod 600 inventories/templ-prod/group_vars/all/vault.yml
chmod 600 inventories/templ-prod/.vault-pass
chmod 600 .state/templ-prod/known_hosts
ssh-add ~/.ssh/swarm-templ-prod
```

Update the provider firewall's controller `/32` to the fresh Mac's public
address for UDP 51830. With the preserved `known_hosts`, public TCP 22 can
remain closed. Then install the controller dependencies and reconnect:

```bash
brew install git go-task/tap/go-task uv wireguard-tools
task setup
task wg-up PROVIDER=templ-prod
task wg-status PROVIDER=templ-prod
task swarm-status PROVIDER=templ-prod
```

The three servers retain their WireGuard and Docker Swarm state. Do not back up
or restore `scwg0.conf`, the launchd plist, or Swarm join tokens: `wg-up`
regenerates the controller configuration and launchd service from the restored
Vault and inventory, while Swarm membership remains on the servers.

If `.state/templ-prod/known_hosts` was not backed up, temporarily allow public TCP 22
from the fresh controller's `/32`. `wg-up` will scan all three public endpoints
and accept them only when their ED25519 fingerprints match
`inventories/templ-prod/hosts.yml`; remove the TCP 22 rule after verification.

## Baseline Docker Swarm

First create a private bucket at an S3-compatible service such as AWS S3,
Cloudflare R2, Backblaze B2 S3, Wasabi, or Tigris. Give a dedicated key only
the object read, write, list, and delete permissions required for that bucket.
Then set the service base endpoint (without a bucket name, query string, or
trailing slash), bucket, signing region, and lookup style in
`inventories/templ-prod/group_vars/all/main.yml`:

```yaml
swarm_backup_s3_endpoint: "https://REPLACE_WITH_SERVICE_ENDPOINT"
swarm_backup_s3_bucket: "REPLACE_WITH_PRIVATE_BUCKET"
swarm_backup_s3_region: "REPLACE_WITH_SIGNING_REGION"
swarm_backup_s3_bucket_lookup: auto  # auto, dns, or path
```

`auto` uses virtual-hosted lookup for AWS/Google endpoints and path lookup for
other S3-compatible services. Use `dns` or `path` only when the selected
service requires it. Template-production storage requires HTTPS.

Add the dedicated credentials to the encrypted template-production Vault:

```bash
task vault-edit PROVIDER=templ-prod
```

```yaml
vault_swarm_backup_s3_access_key: "REPLACE_WITH_ACCESS_KEY"
vault_swarm_backup_s3_secret_key: "REPLACE_WITH_SECRET_KEY"
```

`swarm-up` adds a separate random `vault_swarm_backup_restic_password` and the
per-node `vault_encryption_at_rest_passphrases` map to an older Vault when they
are absent. Back up the encrypted Vault and its matching `.vault-pass` after
that change. The S3 objects cannot be decrypted without the Restic password,
and fscrypt data cannot be unlocked without the matching node passphrase.

After WireGuard is healthy, create the baseline three-manager Swarm:

```bash
task swarm-up PROVIDER=templ-prod
task swarm-status PROVIDER=templ-prod
task verify PROVIDER=templ-prod
```

`swarm-up` installs SHA256-pinned Docker Engine `29.7.2`, Docker CLI `29.7.2`,
and containerd `2.3.3` AMD64 packages from Docker's Ubuntu 26.04 repository. It
also installs the complete SHA512-pinned gVisor `20260810.0` AMD64 bundle and
configures Docker to use `runsc` with gVisor netstack by default.
When `encryption_at_rest: true`, it also provisions and unlocks the fscrypt v2
business-data root described in [encrypted business-data storage](encrypted-at-rest.md)
before starting Docker.
It initializes `templ-prod-1`, joins the other two nodes as managers, and uses only
their `10.217.79.x` WireGuard addresses for manager and data-path advertising.
Do not expose TCP 2377, TCP/UDP 7946, or UDP 4789 through the provider firewall.

All three inventory nodes must have `swarm_availability: active`, and exactly
one must have `swarm_run_on_backup: true`. `swarm-up` reconciles the Docker node
label `run_on_backup=true` on that manager and `run_on_backup=false` on the
other two. It installs SHA256-pinned Restic `0.19.1` for AMD64 and enables the
server-side six-hour backup timer only on the selected node. It verifies or
initializes the encrypted repository under
`<deployment_name>/<inventory_slug>/swarm-state/v1` in the configured S3 bucket.

`verify` checks the pinned Ubuntu, Docker, gVisor, WireGuard, and three-manager
Swarm baseline, including private manager/data-path addresses and requested
scheduling availability. It runs a digest-pinned temporary gVisor job with the
strict `node.labels.run_on_backup==true` constraint, proves the job ran on the
selected manager under `runsc`, and removes the service even when verification
fails. The image may remain in Docker's local cache.

All three managers are normally schedulable. To move backup ownership, change
the old node to `swarm_run_on_backup: false` and the replacement to `true` in
`inventories/templ-prod/hosts.yml`:

```yaml
templ-prod-2:
  swarm_availability: active
  swarm_run_on_backup: true
```

Keep every manager `active` and exactly one `swarm_run_on_backup: true`, then
reconcile and verify:

```bash
task swarm-up PROVIDER=templ-prod
task swarm-status PROVIDER=templ-prod
```

The node label is a placement selector, not a reservation. Every future Swarm
service must use one of these strict constraints:

- Backup-node-specific, interruptible service:
  `node.labels.run_on_backup == true`
- Ordinary service that must stay off the backup node:
  `node.labels.run_on_backup != true`

Do not use a placement preference or omit the constraint: either choice allows
ordinary work to reach the backup manager. Do not run standalone containers on
that manager. A service constrained only to the backup node must tolerate a
short interruption during each cold backup.

Every six hours, the labeled manager requires an exact healthy three-manager
quorum, verifies its own WireGuard Swarm identity, `Active` availability, and
unique `run_on_backup=true` ownership, and refuses to continue if a standalone
container is running there. It temporarily changes itself to `Drain`, waits for
its Swarm tasks to stop, stops only its Docker daemon, and creates a cold archive
of `/var/lib/docker/swarm`. The cleanup path restarts Docker and returns the
same manager to `Active`; no leave or join command and no join token is used.
Only after quorum, availability, and label ownership are restored does it upload
the encrypted Restic snapshot and prune snapshots outside the 30-day window.

`task swarm-status PROVIDER=templ-prod` reports the remote timer and last service
result. `task verify PROVIDER=templ-prod` verifies ownership only on the labeled
manager, the exact six-hour/30-day policy, pinned Restic, and access to the
encrypted repository. It does not force an unscheduled cold backup.

Only Swarm state is captured: Raft state, membership, services, configs,
secrets, and Swarm encryption material. Application volumes, databases,
container images, VPS disks, S3 bucket recovery, and the template-production
Vault require separate backup plans.

To make all three nodes leave the Swarm, remove the baseline gVisor runtime,
and return Docker to `runc` without uninstalling Docker or changing WireGuard,
run:

```bash
task swarm-down PROVIDER=templ-prod
```

This stops Swarm orchestration and any workloads deployed through it. It also
removes the backup service, timer, and node-local credentials, while preserving
every object already stored in S3.

## Additional steps for replacing VPSes

For the required Swarm drain, demotion, removal, and rejoin order when replacing
one cluster member, start with the [node lifecycle runbook](node-lifecycle.md).
The steps below describe the production host and WireGuard identity portion of
that procedure.

When completely replacing the cluster with new base images, the servers will
have new SSH host keys. Preserve the old file for audit, then rebuild
`.state/templ-prod/known_hosts` using the verified replacement fingerprints as
described below.

Replacing a VPS does not automatically rotate its WireGuard identity. The
logical `templ-prod-*` identities and key pairs live in the template-production
Vault, so `wg-up` can install the existing private key for that logical node on
its replacement.
The controller's rendered `scwg0.conf` is then updated with the inventory's
current public endpoint while retaining the matching Vault-backed WireGuard
public key. Do not edit or delete `scwg0.conf` to rotate keys.

Before reusing an existing WireGuard identity, destroy or isolate the old VPS
so that two servers cannot claim the same key and mesh address. For every
replacement VPS:

1. Prepare its `ops` account and trusted sudo access as described above.
2. Record its new public IP or DNS endpoint and its new ED25519 SSH host-key
   fingerprint from the trusted provider console.
3. Update both corresponding values in `inventories/templ-prod/hosts.yml`.
4. Temporarily allow public TCP 22 from the controller's trusted `/32` to all
   three inventory endpoints. Rebuilding the alias file verifies all three
   servers together, and a replacement cannot be reached through WireGuard
   until it has been configured.
5. Preserve the old verified alias file and force a fresh fingerprint-checked
   public host-key scan:

   ```bash
   test ! -e .state/templ-prod/known_hosts.previous
   mv .state/templ-prod/known_hosts .state/templ-prod/known_hosts.previous
   task wg-up PROVIDER=templ-prod
   ```

   The scan succeeds only when each observed host key matches the complete
   `SHA256:...` value recorded in the inventory. If it fails, leave the backup
   intact and resolve the endpoint or fingerprint mismatch through the trusted
   provider console.
6. Run the `wg-status` and three `wg-ssh` checks shown above, then remove the
   temporary public TCP 22 rule. Retain or securely dispose of
   `known_hosts.previous` according to the operator's recovery policy.

If an old VPS or its WireGuard private key is no longer trusted, do not reuse
that identity. Deliberately rotate the matching Vault key pair—or all
template-production mesh identities through the documented reset workflow—only
while public recovery SSH is available. Back up the current Vault pair before
any rotation.

## Reversibly disconnect the controller

To take only the macOS controller off the production mesh:

```bash
task wg-remove PROVIDER=templ-prod
```

This is intentionally narrower than template-local `wg-remove`. It proves the project
launchd definition, preserved `scwg0.conf`, configuration-derived public key,
runtime `utunN` name and socket, and controller address before changing
anything. It then unloads only the project launchd job, stops only that verified
macOS interface, and verifies that both the interface and `10.217.79.1` are
absent.

The command preserves the launchd plist, rendered configuration, encrypted
Vault and password file, and verified `known_hosts`. It does not connect to or
change any production server, server tunnel, firewall, service, or workload.

Reconnect with:

```bash
task wg-up PROVIDER=templ-prod
```

When the preserved `known_hosts` aliases still match all inventory
fingerprints, `wg-up` validates and reuses them without a public SSH scan. It
reloads the preserved controller tunnel first, then reaches the still-running
server tunnels through the private mesh. A fresh controller without that file
still performs the live public host-key bootstrap.

## Reset template-production Vault state

To deliberately delete only the template-production provider Vault and its
matching password file, run:

```bash
task reset PROVIDER=templ-prod CONFIRM=reset-templ-prod
```

This is the template-production reset command. It permanently removes:

- `inventories/templ-prod/group_vars/all/vault.yml`
- `inventories/templ-prod/.vault-pass`

It does not disconnect the controller, delete rendered controller state, or
contact or change a production server. Use `task wg-remove PROVIDER=templ-prod`
first if the controller should also be disconnected. Back up the Vault pair
before resetting it; both files are required to recover the encrypted
WireGuard identities, the Restic repository, and every node's `/srv/secure`
fscrypt policy. With `encryption_at_rest: true`, resetting the only Vault copy
can make production business data permanently inaccessible after the loaded
keys leave memory or the servers reboot.
