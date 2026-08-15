# Add or remove a Swarm node

This runbook covers a controlled, one-for-one replacement of one node in the
existing cluster. Run every controller command from the `swarm/` directory.

## Supported topology

The current automation supports exactly three inventory nodes. Every node is
both a Docker Swarm manager and a worker, every node is `active`, and exactly
one node has `swarm_run_on_backup: true`.

Consequently:

- A node can be removed only as a temporary step in replacing that same
  logical inventory slot.
- The replacement keeps the same `templ-local-*` or `templ-prod-*` inventory
  name and the same WireGuard address.
- A permanent fourth node, a permanent two-node cluster, and worker-only nodes
  are not supported.
- `task swarm-down` is a whole-cluster teardown. Never use it to remove one
  node.

During replacement, the two surviving managers form a quorum of two. Both
must remain healthy and reachable until the third manager has rejoined. The
cold Swarm-state backup intentionally refuses to run while the cluster has
only two members.

This procedure preserves Swarm services, configs, secrets, and Raft state
through the surviving quorum. It does **not** migrate a node's local Docker
volumes, databases, `/srv/secure` contents, or other host-local data. Migrate
or restore that data with the application's own procedure before deleting the
old machine.

## Choose the target and anchor

Set these controller-shell variables to one supported profile, the node being
replaced, and a healthy surviving manager:

```bash
export PROVIDER=templ-prod
export TARGET=templ-prod-2
export ANCHOR=templ-prod-1
```

For a local replacement, use `templ-local` names instead:

```bash
export PROVIDER=templ-local
export TARGET=templ-local-2
export ANCHOR=templ-local-1
```

`TARGET` and `ANCHOR` must be different. Do not continue if another manager is
unavailable.

## 1. Prove the three-manager baseline is healthy

From the controller:

```bash
task wg-status PROVIDER="$PROVIDER"
task swarm-status PROVIDER="$PROVIDER"
task verify PROVIDER="$PROVIDER"
task wg-ssh PROVIDER="$PROVIDER" NODE="$ANCHOR"
```

On the anchor manager, inspect the quorum and workloads:

The controller's `TARGET` variable is not forwarded through SSH. In each
remote manager shell below, set `TARGET_NODE` to the literal inventory name
chosen for `TARGET`; this example uses `templ-prod-2`:

```bash
TARGET_NODE=templ-prod-2
sudo docker node ls
sudo docker service ls
sudo docker node inspect --pretty "$TARGET_NODE"
```

Require one `Leader`, two `Reachable` managers, and no unhealthy services.
Resolve every warning before continuing. Check the target for standalone
containers as well: Swarm `Drain` moves service tasks, but it does not move or
stop standalone containers.

```bash
exit
task wg-ssh PROVIDER="$PROVIDER" NODE="$TARGET"
sudo docker ps
exit
```

Back up any application data that is local to the target.

## 2. Make a survivor the automation anchor

Open `inventories/$PROVIDER/hosts.yml`. The first key under
`wireguard_nodes.hosts` must name a surviving manager because `swarm-up` uses
that node to identify the existing cluster.

If `TARGET` is currently first, move the complete `ANCHOR` mapping before it.
Do not rename either node or change its variables. Keep the new order after
the replacement; the first entry is an automation anchor, not a permanent
Docker leader.

If `TARGET` has `swarm_run_on_backup: true`, move backup ownership to one
survivor in the same edit:

```yaml
swarm_run_on_backup: false  # target
swarm_run_on_backup: true   # exactly one surviving manager
```

Every other node must remain `swarm_run_on_backup: false`, and every
`swarm_availability` must remain `active`. Reconcile and verify the edited
inventory while all three managers are still available:

```bash
task swarm-up PROVIDER="$PROVIDER"
task swarm-status PROVIDER="$PROVIDER"
task verify PROVIDER="$PROVIDER"
```

Do not remove the target if this reconciliation fails.

## 3. Drain the target

Connect to the anchor and drain the target by its Docker node name:

```bash
task wg-ssh PROVIDER="$PROVIDER" NODE="$ANCHOR"
TARGET_NODE=templ-prod-2
sudo docker node update --availability drain "$TARGET_NODE"
sudo docker node inspect --pretty "$TARGET_NODE"
sudo docker node ps "$TARGET_NODE"
sudo docker service ls
```

Wait until replacement service tasks are running elsewhere. A task in
`Shutdown` state is historical and is not itself an error. Use each
application's health check to prove that moving the running tasks did not
break the service.

Do not proceed while a required task is still running on the target or a
replacement task is unhealthy.

## 4. Demote, leave, and remove the old member

Still on the anchor, demote the target before it leaves:

```bash
sudo docker node demote "$TARGET_NODE"
sudo docker node ls
exit
```

Confirm that the target is now a worker and both surviving managers are
reachable. Then make the target leave from the target itself:

```bash
task wg-ssh PROVIDER="$PROVIDER" NODE="$TARGET"
sudo docker swarm leave
exit
```

Remove the stale node record from the anchor:

```bash
task wg-ssh PROVIDER="$PROVIDER" NODE="$ANCHOR"
TARGET_NODE=templ-prod-2
sudo docker node rm "$TARGET_NODE"
sudo docker node ls
exit
```

The cluster is now in a temporary two-manager state. Do not run routine
maintenance, cold backups, or another manager change before completing the
replacement.

If the target is unreachable, first prove that the other two managers still
have quorum. From the anchor, demote the unavailable target and only then use
`docker node rm --force "$TARGET_NODE"`. This is an emergency exception; never
force-remove a reachable manager and never remove a second manager.

## 5. Replace the machine without duplicating its identity

The old machine must be powered off, deleted, or isolated before the
replacement starts using the same logical WireGuard identity and address.

### Template-local

The following commands permanently delete only the target Lima VM and its
disk, then let `lima-up` recreate the missing inventory member:

```bash
test "$PROVIDER" = templ-local
case "$TARGET" in
  templ-local-1|templ-local-2|templ-local-3) ;;
  *) exit 1 ;;
esac
export LIMA_HOME="$HOME/.lima/.templ-local"
limactl list
limactl stop "$TARGET"
limactl delete --tty=false "$TARGET"
unset LIMA_HOME
task lima-up PROVIDER=templ-local
```

Before running `limactl stop`, confirm that the provider-scoped list contains
the exact target selected above. The shell guard refuses every other provider
or instance name.

Do not run `task lima-destroy`; it deletes all three project VMs. The
provider-scoped Lima home is `$HOME/.lima/.templ-local`, not the repository's
old `.l` path and not Lima's shared default profile.

### Template-production

Provision one replacement Ubuntu 26.04 AMD64 server, but preserve the target's
logical inventory name and WireGuard address. Follow [Prepare the
servers](setup-templ-prod.md#prepare-the-servers), then follow [Additional
steps for replacing
VPSes](setup-templ-prod.md#additional-steps-for-replacing-vpses) to:

1. install the existing operator SSH public key and sudo contract;
2. obtain the new ED25519 host-key fingerprint from the trusted provider
   console;
3. update only the target's public endpoint and fingerprint in
   `inventories/templ-prod/hosts.yml`;
4. rebuild the fingerprint-verified `known_hosts`; and
5. reuse the target's Vault-backed WireGuard key only after the old VPS is
   isolated.

Rotate that WireGuard key pair instead of reusing it if the old private key
might be compromised. Do not expose public SSH beyond the temporary,
controller-restricted recovery rule described in the production setup guide.

## 6. Restore the WireGuard member

From the controller:

```bash
task wg-up PROVIDER="$PROVIDER"
task wg-status PROVIDER="$PROVIDER"
task wg-ssh PROVIDER="$PROVIDER" NODE="$TARGET"
exit
```

Do not continue until the controller can reach the replacement through its
private WireGuard address. For template-production, remove the temporary
public TCP 22 firewall rule after the documented mesh checks pass.

## 7. Join the replacement as the third manager

Run the supported reconciler rather than copying a manager join token through
shell history:

```bash
task swarm-up PROVIDER="$PROVIDER"
```

Because the first inventory entry is a surviving manager, `swarm-up` uses its
existing cluster ID, installs the repository-pinned engine and runtime on the
replacement, and joins the inactive target as a manager over WireGuard. It
also restores `active` scheduling and the declared `run_on_backup` labels.

Do not run `docker swarm init` on the replacement. That would create a second,
competing cluster.

## 8. Verify the restored baseline

From the controller:

```bash
task swarm-status PROVIDER="$PROVIDER"
task verify PROVIDER="$PROVIDER"
task wg-ssh PROVIDER="$PROVIDER" NODE="$ANCHOR"
sudo docker node ls
sudo docker service ls
exit
```

Require all of the following before declaring the replacement complete:

- exactly three managers: one `Leader` and two `Reachable`;
- all three managers have `Active` availability;
- all services have their desired replicas;
- exactly one manager has `run_on_backup=true`;
- only that manager owns the enabled backup timer; and
- the complete repository verification succeeds.

Restore application-local data with its application-specific process. If
backup ownership should return to the replacement, change the two inventory
booleans only after this verification, rerun `swarm-up`, and rerun the checks
above.

## Permanent scale-out or scale-in

Do not add an unmanaged fourth member with `docker swarm join`, and do not
leave the repository at two members. Both states violate the automation and
backup contracts. Four managers also require three votes for quorum and do not
tolerate more failures than three managers.

A permanent topology change is an implementation project, not an operator
command. At minimum it must update and test:

- the exact-three assertions in `playbooks/swarm-up.yml` and
  `playbooks/verify.yml`;
- the exact-three manager and quorum validation in
  `roles/swarm_backup/files/swarm-backup-run`;
- `scripts/inventory-node-names.py`, `scripts/lima-node-names.py`, and
  `scripts/prod-known-hosts.py`;
- the selected provider inventory, WireGuard addresses, endpoints, keys,
  ports, MAC addresses, and firewall peer rules; and
- all topology, verification, backup, and teardown tests and documentation.

Prefer an odd manager count. Expanding this all-manager design means moving
from three to five managers; adding worker-only capacity requires a separate
inventory-role model because the current baseline requires every inventory
node to be a manager.

The command order in this runbook follows Docker's current guidance for
[draining a node](https://docs.docker.com/engine/swarm/swarm-tutorial/drain-node/),
[managing and removing nodes](https://docs.docker.com/engine/swarm/manage-nodes/),
and [maintaining manager quorum](https://docs.docker.com/engine/swarm/admin_guide/).
