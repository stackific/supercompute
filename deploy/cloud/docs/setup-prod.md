# Production setup

The `prod` inventory manages a WireGuard mesh between one macOS controller and
an arbitrary number of Ubuntu 26.04 AMD64 VPS nodes. The project does not create
servers or provider firewall rules. Node names, mesh addresses, and endpoints
come from inventory only.

Read `deployment_name` from `deployment.yml` and use inventory slug `prod` (or
whatever `inventories/<slug>/` directory you are configuring). Below,
`<deployment_name>` and `<provider>` mean those values (for example
`templ-cluster` and `prod`).

## Prerequisites

- macOS on Apple Silicon (controller)
- [Task](https://taskfile.dev/installation/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- WireGuard tools (`wg`, `wg-quick`)

```sh
brew install go-task/tap/go-task uv wireguard-tools
cd deploy/cloud
task setup
```

## Prepare the Mac SSH identity (once)

Use an empty passphrase. Back up both key files in your password manager.

```sh
ssh-keygen -t ed25519 -a 100 \
  -f ~/.ssh/<deployment_name>-<provider> \
  -C "<deployment_name> <provider>"
ssh-add ~/.ssh/<deployment_name>-<provider>
pbcopy < ~/.ssh/<deployment_name>-<provider>.pub
```

Set `prod_ssh_private_key_file` in
`inventories/<provider>/group_vars/all/main.yml` to that private key path, or
rely on `ssh-agent` after `ssh-add`.

## Prepare each VPS (provider web console)

Create Ubuntu Server 26.04 AMD64 instances. On each VM, create the inventory SSH
user (sample `ops`), install the Mac public key, and grant passwordless sudo.
Replace `ops` and the sudoers filename if your inventory uses different values.

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

## Fill the production inventory

Edit `inventories/<provider>/hosts.yml` for every deployment host:

- `prod_wireguard_endpoint` — public IPv4 or DNS name (not the mesh address)
- `prod_ssh_host_ed25519_sha256` — complete `SHA256:…` host-key fingerprint

Edit `inventories/<provider>/group_vars/all/main.yml`:

- `provider.image.source`, `prod_default_ssh_user`, optional `prod_ssh_private_key_file`
- `prod_wireguard_node_addresses` — one mesh IP per inventory hostname (any N;
  must stay disjoint from Lima `10.79.0.0/24` and `10.79.1.0/24` on the same Mac)

Example shape (replace placeholders; add or rename hosts as needed):

```yaml
prod-1:
  prod_wireguard_endpoint: "203.0.113.11"
  prod_ssh_host_ed25519_sha256: "SHA256:REPLACE_WITH_COMPLETE_FINGERPRINT"
```

## Provider firewall

Allow inbound UDP **51830** only from the controller's public `/32` and each
server's public `/32`. During initial bootstrap or recovery, also allow inbound
TCP **22** from the controller `/32`; remove that rule after every node answers
`wg-ssh`. Allow TCP **80** and **443** when you deliberately publish HTTP(S).
Leave all other unsolicited inbound traffic denied. Confirm the provider
firewall is stateful.

## Initialize vault and bring up the mesh

```sh
task vault-init PROVIDER=prod
task wg-up PROVIDER=prod
```

`wg-up` fingerprint-pins host keys into `.state/prod/known_hosts`, ensures Vault
WireGuard key pairs (`macos` plus every inventory host), installs the Mac
`scwg0` config and launchd unit, configures each server, and proves mesh SSH.

```sh
task wg-status PROVIDER=prod
task wg-ssh PROVIDER=prod NODE=<inventory_hostname>
```

`wg-ssh` connects from the Mac to the node's private WireGuard address.

Controller-only disconnect (does not change servers):

```sh
task wg-remove PROVIDER=prod
```

## Backup for a fresh computer

Store the following in your personal secret manager. Without them you cannot
decrypt the vault, prove SSH identity to the servers, or rejoin the WireGuard
mesh from a new Mac. Do **not** rely on git for anything marked gitignored.

### Must store (secrets)

| Item | Path / form | Why |
| --- | --- | --- |
| Operator SSH private key | `~/.ssh/<deployment_name>-<provider>` | Proves you are the operator on every node (`ops` / inventory user) |
| Operator SSH public key | `~/.ssh/<deployment_name>-<provider>.pub` | Rebuild authorized_keys or verify the key pair |
| Ansible Vault password | `inventories/<provider>/.vault-pass` | Decrypts WireGuard private keys; **gitignored**—losing this loses the vault contents |

### Must store or already have in git (recovery inputs)

| Item | Where | Why |
| --- | --- | --- |
| Encrypted vault | `inventories/<provider>/group_vars/all/vault.yml` | Holds `vault_prod_wireguard_*` key pairs. Prefer committing it; also keep a secret-manager copy |
| Per-node host-key fingerprints | `SHA256:…` from each `/etc/ssh/ssh_host_ed25519_key.pub` | Must match `prod_ssh_host_ed25519_sha256` in `hosts.yml` for `wg-up` / known_hosts |
| Per-node public endpoints | IPv4 or DNS in `hosts.yml` | WireGuard peer endpoints and bootstrap SSH |
| Inventory + `deployment.yml` | Git clone | Host names, mesh IPs, SSH user, launchd label namespace |

Also note your **Mac’s current public IPv4** used in the provider firewall for UDP
51830 (and temporary TCP 22). A new network location needs that firewall rule
updated before mesh or bootstrap SSH works.

### Do not need to back up (recreated on the new Mac)

These are regenerated by `task wg-up PROVIDER=<provider>` after you restore the
secrets above and clone the repo:

- `.state/<provider>/known_hosts`
- `.state/<provider>/wireguard/<interface>.conf` (e.g. `scwg0.conf`)
- Launchd plist under `/Library/LaunchDaemons/`

### Restore on a fresh Mac

1. Install Task, `uv`, and `wireguard-tools`; clone the repo; `cd deploy/cloud`; `task setup`.
2. Restore the SSH key pair to `~/.ssh/<deployment_name>-<provider>` (mode `0600` on the private key); `ssh-add` it; set `prod_ssh_private_key_file` if you use that path.
3. Restore `inventories/<provider>/.vault-pass` (mode `0600`). Confirm `vault.yml` is present (from git or secret manager).
4. Confirm `hosts.yml` fingerprints and endpoints match what you stored.
5. Update the provider firewall with this Mac’s public `/32` if it changed.
6. Run `task wg-up PROVIDER=<provider>` (temporarily allow TCP 22 from the new Mac if the mesh is down and public SSH was closed).
7. Confirm with `task wg-ssh PROVIDER=<provider> NODE=<inventory_hostname>`.

## Sample mesh addresses

Default stub uses:

| Role | Address |
| --- | --- |
| Mac controller | `10.217.79.1` |
| Inventory nodes | `10.217.79.11+` in `prod_wireguard_node_addresses` |

Interface name on servers: `scwg0`. Listen port: `51830`.
