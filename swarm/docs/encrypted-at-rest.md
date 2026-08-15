# Encrypted business-data storage

This policy is part of the Docker Swarm template and applies identically to
both inventory profiles.

`deployment.yml` controls node-local encryption at rest:

```yaml
encryption_at_rest: true
```

When the flag is `true`, `task swarm-up PROVIDER=<name>` configures fscrypt on
the ext4 filesystem that contains `/srv/secure`, encrypts that directory with
a separate random passphrase for each node, and unlocks it before Docker
starts. The passphrases exist only in the provider's encrypted Ansible Vault.
Back up the Vault and its matching `.vault-pass` together; losing them makes
the node-local data unrecoverable after the keys leave memory.

The first encryption run requires `/srv/secure` to be empty. Automation
refuses existing plaintext data and does not attempt an in-place migration.
It also refuses filesystems other than ext4 instead of creating or formatting
a block device implicitly. See [the VPS encryption self-evaluation](vps-encryption-swarm-self-evaluation.md)
for the threat model, migration guidance, performance checks, and alternatives.

Docker has a project-owned start guard when encryption is enabled. After a
node reboot, Docker remains stopped while `/srv/secure` is locked. Rerun
`task swarm-up PROVIDER=<name>` from the Vault-bearing controller to unlock the
directory and reconcile Docker and Swarm. The unlock key is never installed as
a plaintext server-side key file.

## Business-data volume convention

Every persistent volume containing customer or business data must use a bind
mount rooted at:

```text
/srv/secure/<container-id>
```

`<container-id>` is a stable deployment-controlled workload identifier, not
Docker's ephemeral runtime container ID. Give each workload its own directory,
for example:

```bash
sudo install -d -o 999 -g 999 -m 0700 /srv/secure/customer-db
```

```yaml
services:
  customer-db:
    volumes:
      - /srv/secure/customer-db:/var/lib/postgresql/data
```

The directory must exist with the UID, GID, and mode required by the container
on every node eligible to run that service. Node-local encryption is not
replication or backup: use placement constraints appropriate to the data and
maintain a separate encrypted application-data backup. The existing Restic
timer backs up only `/var/lib/docker/swarm`, not `/srv/secure`.

Setting `encryption_at_rest: false` leaves new deployments unmanaged by
fscrypt. It does not decrypt a directory previously owned by this baseline;
the role refuses that downgrade so encrypted data cannot silently become
unavailable or plaintext.
