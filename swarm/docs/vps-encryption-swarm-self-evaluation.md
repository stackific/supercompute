# VPS Encryption-at-Rest & Docker Swarm Self-Evaluation Checklist

This checklist supports the production profile of the reusable Docker Swarm
template.

Use this checklist when evaluating a VPS for Docker Swarm workloads, especially when the VPS has only a single root disk.

> **Goal:** decide whether the VPS is a good fit for encrypted persistent application data without unnecessarily encrypting Docker image layers, caches, or other disposable data.

---

## 1. Inspect the VPS storage layout

Run:

```bash
findmnt -no SOURCE,FSTYPE,OPTIONS /
df -hT /
lsblk -f
```

### What to look for

Typical root filesystems:

- `ext4` — ideal for `fscrypt`
- `f2fs` — supports `fscrypt`
- `xfs` — use LUKS/dm-crypt instead of fscrypt
- `btrfs` — use LUKS/dm-crypt for a straightforward at-rest encryption layer
- `zfs` — consider native ZFS dataset encryption
- `overlay` — probably means the command was run inside a container rather than on the host

For an existing VPS with one root disk:

```text
ext4/f2fs
  -> fscrypt is usually the simplest option for selected directories

xfs/btrfs/other
  -> use a LUKS container file or rebuild with full-disk LUKS

zfs
  -> consider native ZFS encryption
```

### Example of a good ext4 layout

```text
/dev/vda1  ext4  /
/dev/vda13 ext4  /boot
/dev/vda15 vfat  /boot/efi
```

A second device such as `vdb` may be a provider config ISO rather than usable storage. Always inspect `lsblk -f` before touching a device.

---

## 2. Check available disk space

```bash
df -hT /
```

Example:

```text
Filesystem  Type  Size  Used  Avail  Use%
/dev/vda1   ext4   24G  3.5G    20G   15%
```

For Docker Swarm, leave enough free space for:

- container image layers
- temporary container writes
- package upgrades
- logs
- database growth
- encrypted application data

A VPS with only ~20 GB free may be fine for a small app, but it is not much headroom for a database-heavy workload.

---

## 3. Benchmark crypto performance

Install `cryptsetup` if necessary:

```bash
sudo apt update
sudo apt install cryptsetup
```

On a production VPS, bound the memory-hard PBKDF benchmark to 64 MiB:

```bash
cryptsetup benchmark --pbkdf-memory 65536
```

`--pbkdf-memory` is expressed in KiB, so `65536` limits the Argon2 benchmark
to 64 MiB. It does not limit or invalidate the AES-XTS cipher throughput
results used below.

An unbounded run on a memory-constrained VPS may print all PBKDF2 results and
then end with only `Killed` as it starts the memory-hard Argon2 benchmark. That
usually means the kernel or a cgroup killed `cryptsetup` under memory pressure;
it is not evidence that AES encryption is unsupported. Confirm the cause with:

```bash
sudo journalctl -k -b --since "10 minutes ago" \
  | grep -Ei 'out of memory|oom|killed process'
free -h
swapon --show
```

Use the bounded command above for this evaluation instead of repeatedly
running the unbounded benchmark on a production server.

The most relevant lines for LUKS/dm-crypt are usually:

```text
aes-xts 256b
aes-xts 512b
```

`aes-xts 512b` is commonly used to describe AES-XTS with two 256-bit AES keys.

### Practical AES-XTS interpretation

Use the slower of encryption/decryption as the rough ceiling.

```text
AES-XTS throughput      Rough rating
------------------------------------------
< 300 MiB/s             weak for fast storage
300-700 MiB/s           acceptable
700-1200 MiB/s          good
1200-1800 MiB/s         very good
1800+ MiB/s             excellent for a VPS
```

Example:

```text
aes-xts 512b
Encryption: 1916 MiB/s
Decryption: 1973 MiB/s
```

That is excellent.

### Important

`cryptsetup benchmark` uses memory only.

It does **not** test your disk.

It tells you roughly how fast the CPU can perform the encryption itself.

---

## 4. Ignore PBKDF numbers for steady-state disk speed

You may see:

```text
PBKDF2-sha256
argon2i
argon2id
```

These mainly affect how expensive it is to derive/unlock the encryption key from a passphrase.

They matter during:

```bash
cryptsetup open ...
```

They do **not** represent normal read/write throughput after the encrypted volume is unlocked.

A ~2 second Argon2id unlock is normal and desirable.

---

## 5. Benchmark actual VPS storage

Install `fio`:

```bash
sudo apt install fio
```

### Simple sequential test

Run this only on a filesystem with enough free space:

```bash
fio \
  --name=seq \
  --filename=/tmp/fio-test \
  --size=2G \
  --rw=readwrite \
  --bs=1M \
  --direct=1 \
  --iodepth=16
```

Delete the test file:

```bash
rm -f /tmp/fio-test
```

### Compare disk speed to AES-XTS speed

Example:

```text
Actual disk speed:      700 MiB/s
AES-XTS capability:    1900 MiB/s
```

Crypto is unlikely to be the bottleneck.

General rule:

```text
Disk throughput          Likely crypto impact
------------------------------------------------
< 300 MiB/s              usually negligible
300-700 MiB/s            usually very small
700-1200 MiB/s           small to moderate
1200-1800 MiB/s          potentially noticeable
1800+ MiB/s              crypto may become limiting
```

These are rough screening ranges, not guarantees.

---

## 6. Optional: test random I/O for database workloads

For PostgreSQL/MySQL, sequential throughput is not enough.

Example random 4K read/write test:

```bash
fio \
  --name=rand \
  --filename=/tmp/fio-rand-test \
  --size=2G \
  --rw=randrw \
  --rwmixread=70 \
  --bs=4k \
  --direct=1 \
  --iodepth=32 \
  --numjobs=1 \
  --runtime=60 \
  --time_based \
  --group_reporting
```

Delete the test file:

```bash
rm -f /tmp/fio-rand-test
```

Pay attention to:

- IOPS
- average latency
- 95th/99th percentile latency
- consistency between repeated runs

For databases, latency consistency often matters more than headline sequential MB/s.

---

## 7. Decide what to encrypt in Docker Swarm

Recommended layout:

```text
/
├── /var/lib/docker
│   ├── images
│   ├── overlay/container layers
│   ├── cache
│   └── swarm state
│
└── /srv/secure
    ├── postgres
    ├── mysql
    ├── uploads
    ├── app-data
    └── other sensitive persistent data
```

### Usually encrypt

```text
/srv/secure/postgres
/srv/secure/mysql
/srv/secure/uploads
/srv/secure/app-data
```

Good candidates:

- database data
- user/customer uploads
- private application data
- persistent business data
- files containing personal data
- sensitive logs if they must exist

### Usually do not bother encrypting separately

```text
/var/lib/docker/overlay2
container image layers
build cache
package cache
disposable temporary data
```

Encrypting all of `/var/lib/docker` adds I/O overhead to data that can usually be recreated.

---

## 8. Docker Swarm secrets

Use Docker Secrets for:

- database passwords
- API keys
- TLS private keys
- application secrets

Avoid storing these in `.env` files when Swarm secrets are available.

Example stack fragment:

```yaml
services:
  app:
    image: example/app
    secrets:
      - db_password

secrets:
  db_password:
    external: true
```

---

## 9. Enable Docker Swarm autolock

Docker Swarm encrypts manager Raft state, but autolock improves protection of the key across daemon restarts.

Enable:

```bash
docker swarm update --autolock=true
```

Retrieve/rotate the unlock key when appropriate:

```bash
docker swarm unlock-key
```

After a manager daemon restart, unlock with:

```bash
docker swarm unlock
```

Keep the Swarm unlock key somewhere **outside the VPS**.

---

## 10. ext4: check whether fscrypt is suitable

If `/` is ext4:

```bash
findmnt -no FSTYPE /
```

Expected:

```text
ext4
```

Install:

```bash
sudo apt update
sudo apt install fscrypt
```

Initialize fscrypt configuration:

```bash
sudo fscrypt setup
```

Check root filesystem status:

```bash
sudo fscrypt status /
```

Check ext4 features:

```bash
sudo tune2fs -l "$(findmnt -no SOURCE /)" | grep 'Filesystem features'
```

Look for:

```text
encrypt
```

---

## 11. Enable the ext4 encryption feature if missing

First confirm the root source:

```bash
findmnt -no SOURCE /
```

Example:

```text
/dev/vda1
```

Then:

```bash
sudo tune2fs -O encrypt /dev/vda1
```

Verify:

```bash
sudo tune2fs -l /dev/vda1 | grep 'Filesystem features'
```

You should see:

```text
encrypt
```

> **Warning:** Always confirm the correct device before running filesystem-management commands.

---

## 12. Initialize fscrypt on `/`

```bash
sudo fscrypt setup /
```

For a server, allowing only root to manage fscrypt metadata is usually reasonable.

---

## 13. Encrypt `/srv/secure`

The directory must be empty when the policy is first applied.

Create it:

```bash
sudo mkdir -p /srv/secure
```

Encrypt it:

```bash
sudo fscrypt encrypt /srv/secure
```

For a VPS, a custom passphrase is usually preferable to tying encryption directly to a normal Linux login password.

Check status:

```bash
sudo fscrypt status /srv/secure
```

---

## 14. Create application directories inside it

After `/srv/secure` is encrypted and unlocked:

```bash
sudo mkdir -p \
  /srv/secure/postgres \
  /srv/secure/mysql \
  /srv/secure/uploads \
  /srv/secure/app-data
```

---

## 15. Use encrypted paths in Docker Swarm

Example PostgreSQL bind mount:

```yaml
services:
  postgres:
    image: postgres:17
    volumes:
      - /srv/secure/postgres:/var/lib/postgresql/data
```

Example application uploads:

```yaml
services:
  app:
    image: example/app
    volumes:
      - /srv/secure/uploads:/app/uploads
```

---

## 16. Lock and unlock fscrypt

Unlock:

```bash
sudo fscrypt unlock /srv/secure
```

Lock:

```bash
sudo fscrypt lock /srv/secure
```

Check status:

```bash
sudo fscrypt status /srv/secure
```

Docker services depending on those files should start only after the directory is unlocked.

---

## 17. If `/srv/secure` already contains data

fscrypt does **not** encrypt existing files in place.

Stop the relevant Docker workload first.

Example:

```bash
docker stack rm mystack
```

Move the old directory:

```bash
sudo mv /srv/secure /srv/secure-old
```

Create a new empty encrypted directory:

```bash
sudo mkdir /srv/secure
sudo fscrypt encrypt /srv/secure
```

Copy data into it:

```bash
sudo cp -a /srv/secure-old/. /srv/secure/
```

Verify the application thoroughly before deleting the old copy.

Example:

```bash
sudo rm -rf /srv/secure-old
```

> On SSD/NVMe storage, deleting plaintext files does not guarantee that every old physical flash block becomes unrecoverable because of wear leveling.

---

## 18. If the root filesystem is not ext4/f2fs

A practical fallback is a LUKS container file.

Example:

```bash
sudo fallocate -l 10G /srv-secure.img
```

Encrypt:

```bash
sudo cryptsetup luksFormat --type luks2 /srv-secure.img
```

Open:

```bash
sudo cryptsetup open /srv-secure.img srv_secure
```

Create filesystem:

```bash
sudo mkfs.ext4 /dev/mapper/srv_secure
```

Create mountpoint:

```bash
sudo mkdir -p /srv/secure
```

Mount:

```bash
sudo mount /dev/mapper/srv_secure /srv/secure
```

Close later:

```bash
sudo umount /srv/secure
sudo cryptsetup close srv_secure
```

### Tradeoffs of a LUKS container file

Advantages:

- works on top of XFS/Btrfs/ext4/etc.
- gives block-level encryption
- easy to isolate sensitive application data

Disadvantages:

- fixed/managed container size
- another filesystem layer
- resizing is more involved
- automatic unlock requires careful key management

---

## 19. Full-root LUKS

Use full-root LUKS only when you actually need the whole operating system encrypted.

Typical layout:

```text
EFI/boot
└── unencrypted

root filesystem
└── LUKS2 encrypted
```

For an already-running VPS this usually requires:

1. backup
2. provider rescue/recovery boot
3. repartition/reformat
4. create LUKS
5. reinstall/restore Linux
6. configure initramfs
7. arrange remote/manual unlock

Do not attempt `cryptsetup luksFormat` against the live root partition.

---

## 20. Key-management rule

Do not defeat your own encryption by storing the only unlock key in plaintext on the same unencrypted VPS filesystem.

Bad pattern:

```text
encrypted application data
        ↑
unlock key stored in /root/keyfile
        ↑
same VPS root disk
```

Better:

- manually enter a passphrase after reboot
- keep recovery material off-server
- use an external KMS where appropriate
- use a secure remote-unlock design
- use hardware-backed key release only when the VPS platform provides a meaningful trust boundary

---

## 21. Backups and snapshots

Encryption of `/srv/secure` does not automatically mean every backup is safe.

Evaluate:

- VPS snapshots
- provider backups
- database dumps
- `pg_dump`
- `mysqldump`
- rsync copies
- object-storage backups
- off-site archives

Ask:

```text
Is the backup encrypted before it leaves my VPS?
Who controls the encryption key?
Can the provider decrypt the backup?
Does the backup contain plaintext database dumps?
```

Application-level backups should ideally be encrypted independently before upload.

---

## 22. Provider encryption-at-rest questions

Provider policies change, so check current documentation for the exact product.

Do not assume that:

```text
"cloud provider"
=
"root VPS disk is encrypted at rest"
```

Ask specifically:

```text
1. Is the VPS/root/local disk encrypted at rest?

2. Is encryption applied to:
   - live local disks?
   - block storage?
   - snapshots?
   - automated backups?
   - temporary/migration copies?

3. Who manages the encryption keys?

4. Can provider staff/infrastructure access plaintext while the VM is running?

5. Is encryption guaranteed contractually or only described as an implementation detail?

6. Are deleted/discarded disks cryptographically erased?

7. Are backups encrypted using separate keys?

8. Is encryption available only on certain product tiers?
```

Provider-managed encryption and guest-controlled encryption solve different problems.

---

## 23. Understand the threat model

Guest-side encryption at rest is strongest against:

- offline copies of disks
- stolen/decommissioned storage
- snapshots obtained without the key
- backups obtained without the key
- accidental exposure of raw storage

It does **not** fully protect against an attacker or infrastructure operator that can inspect a running VM after the encryption key has been loaded.

When the filesystem is unlocked:

```text
encrypted disk
     ↓
kernel holds key
     ↓
applications read plaintext
```

---

## 24. Quick VPS scoring sheet

### Filesystem

```text
ext4/f2fs + fscrypt available       +2
other FS but LUKS practical         +1
difficult/no encryption path         0
```

### AES-XTS crypto throughput

```text
1800+ MiB/s                         +3
1200-1800 MiB/s                     +2
700-1200 MiB/s                      +1
300-700 MiB/s                        0
<300 MiB/s                          -1
```

### Disk headroom

```text
>50% free                           +2
25-50% free                         +1
15-25% free                          0
<15% free                           -1
```

### Storage performance relative to crypto

```text
crypto > 2x disk throughput         +2
crypto > disk throughput            +1
roughly equal                        0
crypto slower than disk             -1
```

### Operational fit

```text
manual unlock acceptable            +1
external KMS available              +1
off-site recovery key stored        +1
encrypted backups                   +2
provider root disk explicitly encrypted +1
provider backup encryption verified +1
```

### Rough interpretation

```text
10+     excellent fit
7-9     very good
4-6     workable
1-3     investigate weaknesses
<=0     poor fit for sensitive workloads
```

This score is only a convenience. A single critical failure—such as unencrypted backups containing sensitive database dumps—can matter more than the total score.

---

## 25. Fast evaluation command bundle

Run these on a candidate VPS:

```bash
echo '=== ROOT FS ==='
findmnt -no SOURCE,FSTYPE,OPTIONS /

echo
echo '=== SPACE ==='
df -hT /

echo
echo '=== BLOCK DEVICES ==='
lsblk -f

echo
echo '=== CPU AES FLAG ==='
grep -m1 -o '\baes\b' /proc/cpuinfo || echo 'AES CPU flag not shown'

echo
echo '=== CRYPTSETUP BENCHMARK ==='
cryptsetup benchmark --pbkdf-memory 65536
```

Then run `fio` separately:

```bash
fio \
  --name=seq \
  --filename=/tmp/fio-test \
  --size=2G \
  --rw=readwrite \
  --bs=1M \
  --direct=1 \
  --iodepth=16
```

Clean up:

```bash
rm -f /tmp/fio-test
```

---

## 26. Preferred architecture for a small Docker Swarm VPS

```text
VPS root disk
│
├── /boot
├── /
│   ├── /var/lib/docker
│   │   ├── images
│   │   ├── cache
│   │   └── disposable layers
│   │
│   └── /srv/secure
│       ├── postgres
│       ├── mysql
│       ├── uploads
│       └── app-data
│
├── Docker Secrets
│   └── credentials / API keys / TLS keys
│
└── Swarm manager
    └── autolock enabled
```

For an ext4 VPS with strong AES-XTS performance, this is usually a good balance between:

- security
- performance
- simplicity
- recoverability
- Docker operational convenience

---

## 27. Final decision checklist

Before using a VPS for sensitive Docker Swarm workloads, confirm:

- [ ] Root filesystem identified
- [ ] Encryption method selected
- [ ] AES-XTS benchmark acceptable
- [ ] Real disk benchmark acceptable
- [ ] Database/random-I/O latency acceptable
- [ ] Enough disk headroom remains
- [ ] `/srv/secure` encrypted before sensitive data is written
- [ ] Database paths live under `/srv/secure`
- [ ] Uploads/private files live under `/srv/secure`
- [ ] Docker image/cache storage remains outside unless needed
- [ ] Docker Secrets used for credentials
- [ ] Swarm autolock enabled on managers
- [ ] Unlock/recovery key stored off-server
- [ ] Backup encryption verified
- [ ] Snapshot encryption verified
- [ ] Provider root-disk policy verified
- [ ] Provider backup policy verified
- [ ] Threat model understood
- [ ] Reboot/unlock procedure tested
- [ ] Restore procedure tested
