# Encrypted business-data storage

`deployment.yml` controls node-local encryption at rest:

```yaml
encryption_at_rest: true
```

When the flag is `true`, `task secure-up PROVIDER=<name>` (after `wg-up`)
installs the SHA256-pinned Ubuntu Resolute `fscrypt` package only if it is not
already at the pinned version, enables ext4 encryption on the filesystem that
contains `/srv/secure`, encrypts that empty directory with a separate random
passphrase per node, and unlocks it. Passphrases live only in the provider's
encrypted Ansible Vault on the controller. They are never written as a keyfile
on the guest.

Back up the Vault and its matching `.vault-pass` together; losing them makes
node-local data under `/srv/secure` unrecoverable after keys leave memory.

The first encryption run requires `/srv/secure` to be empty. Automation refuses
existing plaintext data and does not attempt an in-place migration. It also
refuses filesystems other than ext4 instead of creating or formatting a block
device.

After a node reboot, `/srv/secure` is locked until you rerun
`task secure-up PROVIDER=<name>` from the Vault-bearing controller. There is no
guest boot auto-unlock (that would require storing the passphrase on the node).

## Commands

```sh
task wg-up PROVIDER=local
task secure-up PROVIDER=local
task secure-status PROVIDER=local
```

`secure-up` is one shot: vault-ensure passphrases → install pinned `fscrypt` if
needed → encrypt if needed → unlock if locked. Later runs are idempotent.

Ensure passphrases without touching nodes:

```sh
task vault-secure-ensure PROVIDER=local
```

## Business-data volume convention

`/srv/secure` itself is `root:root` mode `0700`. Ordinary users (including
`ops`) cannot `cd` into it; that is intentional. Workloads do **not** need
permission on the parent directory. Create a **child** directory owned by the
numeric UID/GID the container process runs as, then bind-mount only that child.

Persistent customer or business data on a node should live under:

```text
/srv/secure/<workload-id>
```

`<workload-id>` is a stable deployment-controlled name (for example
`customer-db`), not Docker's ephemeral runtime container ID.

### What UID `999` means

Linux identifies users by number (UID), not by the name inside the image.
Many official images run as a non-root UID such as `999` (common for
PostgreSQL's `postgres` user in the image). That number is **not** a special
Docker user and may differ per image — confirm with the image docs or:

```sh
docker run --rm --entrypoint id postgres:16
```

Use whatever UID/GID that prints (for example `uid=999(postgres) gid=999(postgres)`).

### Creating a workload directory

After `secure-up` has unlocked `/srv/secure`, as root on the node:

```sh
sudo install -d -o 999 -g 999 -m 0700 /srv/secure/customer-db
```

That command:

| Part | Meaning |
| --- | --- |
| `install -d` | Create the directory (and parents if needed), like a careful `mkdir` |
| `-o 999` | Set owner UID to `999` (the container user) |
| `-g 999` | Set group GID to `999` |
| `-m 0700` | Mode `rwx------` — only that UID can read/write the data |
| `/srv/secure/customer-db` | Host path you will bind-mount into the container |

Docker (running as root on the host) can open `/srv/secure/...` for the mount
even though `ops` cannot browse `/srv/secure`. Inside the container, the
process only needs rights on the mounted path.

Example compose bind mount:

```yaml
services:
  customer-db:
    image: postgres:16
    volumes:
      - /srv/secure/customer-db:/var/lib/postgresql/data
```

Create the directory with matching ownership on every node that may run that
service. Node-local encryption is not replication or backup; maintain a
separate encrypted application-data backup when you place data there.

Setting `encryption_at_rest: false` leaves new deployments unmanaged by
fscrypt. It does not decrypt a directory previously owned by this deployment;
the role refuses that downgrade so encrypted data cannot silently become
unavailable or plaintext.
