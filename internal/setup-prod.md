# Production setup

The `prod` inventory manages a WireGuard mesh between one macOS controller and
an arbitrary number of Ubuntu 26.04 AMD64 **public endpoint** hosts
(`provider.platform: public`). The project does not create servers or provider
firewall rules. Node names, mesh addresses, and endpoints come from inventory
only. `inventories/prod/` is operator-local (gitignored); restore it from your
backup when needed.

Read `deployment_name` from `deployment.yml` and use inventory slug `prod` (or
whatever `inventories/<slug>/` directory you are configuring). Below,
`<deployment_name>` and `<provider>` mean those values (for example
`sc` and `prod`).

## Prerequisites

- macOS on Apple Silicon (controller)
- [Task](https://taskfile.dev/installation/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- WireGuard tools (`wg`, `wg-quick`)

```sh
brew install go-task/tap/go-task uv wireguard-tools
# from this repository / worktree root
task setup
```

`task setup` installs the locked Ansible venv and ensures `cloudflared` is on
PATH (Homebrew on macOS) for **non-Lima** roaming SSH bootstrap. Lima guests
under `dev` use Lima-local SSH instead — see [setup-dev.md](setup-dev.md).



## Prepare the Mac SSH identity (once)

Use an empty passphrase. Back up both key files in your password manager.

```sh
ssh-keygen -t ed25519 -a 100 \
  -f ~/.ssh/<deployment_name>-<provider> \
  -C "<deployment_name> <provider>"
ssh-add ~/.ssh/<deployment_name>-<provider>
pbcopy < ~/.ssh/<deployment_name>-<provider>.pub
```



## Prepare each static public host (provider web console)

Create Ubuntu Server 26.04 AMD64 instances. On each VM, create the inventory SSH
user (sample `ops`), install the Mac public key, and grant passwordless sudo.
Use the **same** username you will set as `prod_default_ssh_user` in the next
section (sample `ops`).

```sh
sudo adduser --disabled-password --gecos '' ops
sudo install -d -o ops -g ops -m 0700 /home/ops/.ssh
sudo tee /home/ops/.ssh/authorized_keys >/dev/null
```

Paste the public key from the clipboard, press Control+D, then:

```sh
sudo chown ops:ops /home/ops/.ssh/authorized_keys
sudo chmod 600 /home/ops/.ssh/authorized_keys
printf '%s\n' 'ops ALL=(ALL) NOPASSWD:ALL' | \
  sudo tee /etc/sudoers.d/90-<deployment_name>-ops >/dev/null
sudo chmod 440 /etc/sudoers.d/90-<deployment_name>-ops
sudo visudo -cf /etc/sudoers.d/90-<deployment_name>-ops
sudo -u ops sudo -n true
```

`visudo -cf` should report `parsed OK`.

### Verify the operator key fingerprint

On the Mac:

```sh
ssh-keygen -lf ~/.ssh/<deployment_name>-<provider>.pub
```

On the VM:

```sh
sudo ssh-keygen -lf /home/ops/.ssh/authorized_keys
```

The `SHA256:…` lines must match.

### Record the SSH host key (password manager + inventory)

On each VM:

```sh
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Store the full `SHA256:…` value in your password manager. Put the same value in
`inventories/<provider>/hosts.yml` as `prod_ssh_host_ed25519_sha256` for that
host. This is the **server** host key, not the operator key from
`authorized_keys`.

## Fill the production inventory (required before up)

Set the SSH user and key path before the first `up`. A wrong
`prod_default_ssh_user` causes SSH failures such as
`wronguser@…: Permission denied`.

### 1. `group_vars/all/main.yml` (SSH user + private key)

Edit `inventories/<provider>/group_vars/all/main.yml` and set at least:

```yaml
prod_default_ssh_user: ops
prod_ssh_private_key_file: "{{ lookup('ansible.builtin.env', 'HOME') }}/.ssh/{{ deployment_name }}-{{ inventory_slug }}"
```

- `prod_default_ssh_user` must match the Linux user you created on every static host
(sample `ops`).
- `prod_ssh_private_key_file` should use the form above (Ansible and `ssh`
both expand it). A leading `~` is **not** expanded; do not hardcode only a
tilde path.
- Optionally replace `provider.image.source` (`REPLACE_WITH_PROVIDER_IMAGE_ID`)
with your provider’s image id when you use provider image automation.
- Mesh IPs are **not** in this file; set `prod_wireguard_address` per host in
`hosts.yml` (choose a CIDR that does not overlap other meshes on this Mac).



### 2. `hosts.yml` (endpoints + fingerprints + mesh IPs)

Edit `inventories/<provider>/hosts.yml` for every deployment host. **Add or
remove hosts only here** — Vault WireGuard keys, known_hosts, and peer configs
follow this host set on the next `up`.

```yaml
static-1:
  prod_wireguard_endpoint: "203.0.113.11"
  prod_ssh_host_ed25519_sha256: "SHA256:…"
  prod_wireguard_address: 10.217.79.11
```

- `prod_wireguard_endpoint` — public IPv4 or DNS name (not the mesh address)
- `prod_ssh_host_ed25519_sha256` — complete `SHA256:…` from
`/etc/ssh/ssh_host_ed25519_key.pub` on that VM
- `prod_wireguard_address` — unique mesh IP in `prod_wireguard_network_cidr`
  (controller uses `prod_wireguard_controller_address`, usually `.1`)



### 3. Prove bootstrap SSH from the Mac

Before `up`, confirm the inventory user and key work (replace host and paths):

```sh
ssh -i ~/.ssh/<deployment_name>-<provider> -o IdentitiesOnly=yes \
  ops@203.0.113.11 true
```

If this fails, fix keys/user/firewall first. Matching key fingerprints alone is
not enough when the SSH user or key path is wrong.

## Provider firewall

**Static hub only (no roaming hosts):** allow inbound UDP **51830** from the
controller's public `/32` and each server's public `/32`.

**With roaming hosts:** each static hub must accept inbound UDP **51830** from a wide
enough source set (often the public internet). Roaming public IPs change and
will not stay in a fixed peer `/32` list. See
[roaming-nodes.md](roaming-nodes.md) §7.

During initial bootstrap or recovery, also allow inbound TCP **22** from the
controller `/32`; remove that rule after every stable node answers `ssh`.
Allow TCP **80** and **443** when you deliberately publish HTTP(S) for other
workloads. For `test-app.stackific.com` GeoDNS, allow inbound UDP/TCP **53** on
`static-1` so public resolvers can reach PowerDNS (answers are WireGuard A
records). Leave all other unsolicited inbound traffic denied. Confirm the
provider firewall is stateful. The Mac does not need inbound UDP **51830**
(roaming and the Mac reach each other through the static hub).

## Initialize vault and bring up the mesh

```sh
task vault-init PROVIDER=prod
task up PROVIDER=prod
```

`up` fingerprint-pins host keys into `.state/prod/known_hosts`, ensures Vault
WireGuard key pairs (`macos` plus every inventory host), installs the Mac
`scwg0` config and launchd unit, configures each server, and proves mesh SSH
(including roaming↔roaming via the static hub when roaming hosts exist). With
any `wireguard_roaming: true` host, it also enables hub forwarding and runs
`wg syncconf` so live `AllowedIPs` match the rendered conf — details in
[roaming-nodes.md](roaming-nodes.md) §6.

```sh
task wg-status PROVIDER=prod
task ssh PROVIDER=prod NODE=<inventory_hostname>
```

`ssh` connects from the Mac to the node's private WireGuard address.

Controller-only disconnect (does not change servers):

```sh
task wg-remove PROVIDER=prod
```

## Cluster services (gVisor, Docker Engine, GeoDNS)

After the mesh is up, install per-node cluster software with:

```sh
task vault-edit PROVIDER=prod
# under deployment_vault.secrets set:
#   maxmind_account_id: "..."
#   maxmind_license_key: "..."
task up PROVIDER=prod
```

`up` installs **gVisor** (`runsc`), **Docker Engine** (`docker-ce`,
`docker-ce-cli`, `containerd.io`, `docker-buildx-plugin` from Docker’s apt
repo), and **PowerDNS** with the GeoIP backend plus MaxMind `geoipupdate`
(weekly timer). There is no HTTP reverse proxy in this role.

Clients resolve the public name **`test-app.stackific.com`**. PowerDNS is
authoritative for that zone and returns a **WireGuard** A record: for NA/SA,
an equal-weight random choice among roaming mesh IPs (`roaming-1` /
`roaming-2` / …); otherwise `static-1`. Answers are mesh IPs — useful for
mesh-side consumers, not public HTTP.

### Cloudflare NS delegation (once)

PowerDNS on `static-1` also listens on the static public IP for UDP/TCP **53**.
At the parent zone (`stackific.com`), create **DNS-only (grey cloud)** records.
Do **not** orange-cloud these — Cloudflare’s proxy is HTTP(S) only and will
break authoritative DNS and mesh GeoDNS ([proxy status](https://developers.cloudflare.com/dns/proxy-status/),
[limitations](https://developers.cloudflare.com/dns/proxy-status/limitations/)):

1. `ns1.stackific.com` → **A** → `static-1` public IPv4 (**DNS-only**)
2. `test-app.stackific.com` → **NS** → `ns1.stackific.com` (NS is never proxied;
   do not also create a proxied A/CNAME for `test-app`)

Allow inbound UDP/TCP **53** to `static-1` in the provider firewall (world or
at least public resolvers). Tunnel SSH hostnames (`ubu26-nas.stackific.com`,
`ubu26-desk.stackific.com`) stay separate Cloudflare Tunnel / Access routes.

### Verify from a mesh peer (or dig @ static public :53)

```sh
dig +short test-app.stackific.com A
# → 10.217.79.12 or 10.217.79.13 (NA/SA, random) or 10.217.79.11 (elsewhere)

# On a node after cluster-up:
runsc --version
docker version
```

Undo with:

```sh
task down PROVIDER=prod CONFIRM=down-prod
```

## Roaming nodes (dynamic IP)

To join Ubuntu 26.04 hosts with a changing public IP (inventory names
`roaming-1`, `roaming-2`, …), follow the Cloudflare Tunnel SSH bootstrap in
[roaming-nodes.md](roaming-nodes.md). Roaming peers always initiate WireGuard;
do not port-forward UDP 51830 inbound on the home router. Widen static hub UDP
**51830** as in the firewall section above before `up` with roaming hosts.
After join, Mac↔roaming and spoke↔spoke stay hub-relayed through `static-1`
(no published roaming Endpoint); adding another `roaming-N` is inventory-only
plus `up` / optional `up`.

## Backup for a fresh computer

Store the following in your personal secret manager. Without them you cannot
decrypt the vault, prove SSH identity to the servers, or rejoin the WireGuard
mesh from a new Mac. Do **not** rely on git for anything marked gitignored.

### Must store (secrets)


| Item                     | Path / form                               | Why                                                                                                                        |
| ------------------------ | ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Operator SSH private key | `~/.ssh/<deployment_name>-<provider>`     | Proves you are the operator on every node (`ops` / inventory user)                                                         |
| Operator SSH public key  | `~/.ssh/<deployment_name>-<provider>.pub` | Rebuild authorized_keys or verify the key pair                                                                             |
| Ansible Vault password   | `inventories/<provider>/.vault-pass`      | Decrypts WireGuard private keys; **gitignored**—losing this loses the vault contents |




### Must store or already have in git (recovery inputs)


| Item                           | Where                                                    | Why                                                                                                                                        |
| ------------------------------ | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Encrypted vault                | `inventories/<provider>/group_vars/all/vault.yml`        | Holds `vault_prod_wireguard_*` key pairs. Prefer committing it; also keep a secret-manager copy |
| Per-node host-key fingerprints | `SHA256:…` from each `/etc/ssh/ssh_host_ed25519_key.pub` | Must match `prod_ssh_host_ed25519_sha256` in `hosts.yml` for `up` / known_hosts                                                         |
| Per-node public endpoints      | IPv4 or DNS in `hosts.yml`                               | WireGuard peer endpoints and bootstrap SSH                                                                                                 |
| Inventory + `deployment.yml`   | Git clone                                                | Host names, mesh IPs, SSH user, launchd label namespace                                                                                    |


Also note your **Mac’s current public IPv4** for temporary TCP **22** to each
static host during bootstrap/recovery. Update that `/32` when the Mac’s public address
changes. With roaming, hub UDP **51830** is not limited to the Mac `/32` (see
firewall section above).

### Do not need to back up (recreated on the new Mac)

These are regenerated by `task up PROVIDER=<provider>` after you restore the
secrets above and clone the repo:

- `.state/<provider>/known_hosts`
- `.state/<provider>/wireguard/<interface>.conf` (e.g. `scwg0.conf`)
- Launchd plist under `/Library/LaunchDaemons/`



### Restore on a fresh Mac

1. Install Task, `uv`, and `wireguard-tools`; clone the repo (or this worktree); `task setup` (also installs `cloudflared` on macOS).
2. Restore the SSH key pair to `~/.ssh/<deployment_name>-<provider>` (mode `0600` on the private key); `ssh-add` it; set `prod_ssh_private_key_file` if you use that path.
3. Restore `inventories/<provider>/.vault-pass` (mode `0600`). Confirm `vault.yml` is present (from git or secret manager).
4. Confirm `hosts.yml` fingerprints and endpoints match what you stored.
5. Update the provider firewall with this Mac’s public `/32` if it changed.
6. Run `task up PROVIDER=<provider>` (temporarily allow TCP 22 from the new Mac if the mesh is down and public SSH was closed).
7. Confirm with `task ssh PROVIDER=<provider> NODE=<inventory_hostname>`.



## Sample mesh addresses

Default stub uses:


| Role            | Address                                                         |
| --------------- | --------------------------------------------------------------- |
| Mac controller  | `10.217.79.1` (`prod_wireguard_controller_address` in main.yml) |
| Inventory nodes | `prod_wireguard_address` per host in `hosts.yml` (e.g. `.11+`)  |


Interface name on servers: `scwg0`. Listen port: `51830`.

```code
# From a static node, ping macOS's address
ping -c 10 -I scwg0 10.217.79.1

# < 20 ms: Excellent (same metro / nearby region)
# 20–50 ms: Very good (typical same-country / nearby DC)
# 50–100 ms: Fine for SSH, Ansible, mesh ops
# 100–200 ms: Usable; feel a bit of lag on interactive work
# > 200 ms: Cross-ocean / congested path; still OK for automation, poor for “snappy” shells
```

