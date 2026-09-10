# Roaming WireGuard nodes (dynamic IP)

This guide is the operator runbook for adding Ubuntu **26.04** amd64 machines
with a **changing public IP** (typically home lab VMs) to a **public-endpoint**
WireGuard mesh (usually operator `prod`). Stable static hosts also run Ubuntu
**26.04**, with fixed `public_ip` values.

**Lima guests (`node_lima_guest: true`, e.g. `dev-lima` `roaming-1`) do not use this
guide.** They still dial a public static WireGuard `Endpoint` (build-up hub,
then the shared roaming dial helper), but bootstrap Ansible uses **Lima-local
SSH** (not rathole). Fingerprints for those guests are auto-filled by
`lima-up ENV=dev-lima` / `lima-host-fingerprints ENV=dev-lima` — see [lima.md](lima.md). Do
not set `bootstrap_ssh_host` on Lima guests.

Inventory hostnames: stable public hosts as `static-1`, `static-2`, …; roaming as
`roaming-1`, `roaming-2`, … (not `home-*` / `prod-*`).

**WireGuard rule:** roaming nodes **always initiate**. Stable peers (static
public hosts, Mac) never dial the roaming node. Open UDP **51830** and TCP
**2333** on the **static hub** — see §1 and
[Adding a roaming node](../docs/src/content/docs/guides/adding-roaming-node.mdx).

**Bootstrap SSH (non-Lima roaming only):** use **rathole** on the first static
hub. The roaming VM dials out to the hub; the Mac/GHA jump through
`127.0.0.1:(61000 + last octet of private_address)` on that hub. Rathole does
**not** carry `scwg0` UDP; after join, day-2 mesh SSH uses WireGuard addresses.

`up` syncs `.state` (known_hosts + mesh configs) from `hosts.yml`. For
non-Lima `roaming: true` it uses the rathole jump (not a public WG endpoint).
Fill inventory, open hub TCP **2333**, run `rathole-client-bootstrap`, install
the client, and prove jump SSH before `up`. Mesh address lives on each host as
`private_address`.

## 0. What you are building

- Existing **static public** nodes: Ubuntu 26.04, stable public IPs, already on the mesh.
- **Roaming** node(s): Ubuntu 26.04 amd64, dynamic public IP, same mesh.
- Mac controller: unchanged (no rathole binary on the Mac).
- Bootstrap path: roaming rathole client → hub rathole server → SSH `ProxyCommand` jump.

## 1. Prerequisites

1. Prod mesh already works: `task ssh ENV=prod NODE=static-1` succeeds.
2. Operator SSH key and vault as in [setup-prod.md](setup-prod.md).
3. `task setup` has fetched the SHA-pinned rathole Linux amd64 binary
   (`.vendor/rathole/rathole`).
4. Hub firewall: inbound **TCP 2333** (`rathole_control_port`) and **UDP 51830**
   from a wide source (home IPs change). Optional on the hub: `ufw allow 2333/tcp`
   and `ufw allow 51830/udp`.
5. On the roaming Ubuntu VM: console or LAN SSH once, to run the generated
   install script. Do not port-forward the home router.

## 2. Prepare the roaming VM (once per machine)

On the roaming VM (console or any existing SSH):

1. Ubuntu **26.04** amd64.
2. Create the same inventory user as prod (example `ops`), install the Mac
   public key, passwordless sudo — same steps as setup-prod “Prepare each
   static public host”, adapted for this host.
3. Confirm `sshd` listens on port **22** on localhost (default).
4. Confirm outbound UDP and TCP work (default on most home routers).
5. Record the host-key fingerprint from the console:

```sh
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

## 3. Inventory values

In `inventories/prod/hosts.yml`:

```yaml
roaming-1:
  roaming: true
  ssh_ed25519_sha256: "SHA256:…"
  private_address: 10.217.79.21   # free address in 10.217.79.0/24
  # no public_ip — roaming never publishes a WG dial-in address
  # no bootstrap_ssh_host — rathole jump is derived from the static hub
```

Add or remove `roaming-N` only in `hosts.yml`; peer configs, Vault keys,
hub `AllowedIPs`, and mesh verification all follow every host with
`roaming: true`.

## 4. Hub server + client install script

```sh
task rathole-client-bootstrap ENV=prod NODE=roaming-1
```

That ensures vault Noise keys and the per-host token, installs **rathole
server** on `static-1` over public SSH, and writes
`.state/prod/rathole/roaming-1-install.sh`.

Copy the script to the roaming VM (LAN `scp`, or USB/console paste) and run it
as root:

```sh
scp .state/prod/rathole/roaming-1-install.sh ops@<roaming-lan-ip>:
ssh -t ops@<roaming-lan-ip> 'sudo bash ~/roaming-1-install.sh'
```

The client retries until the hub server is reachable on TCP **2333**.

Confirm on the roaming VM:

```sh
sudo systemctl status rathole-client
```

Confirm on the hub:

```sh
sudo systemctl status rathole-server
ss -tlnp | grep 2333
ss -tlnp | grep 127.0.0.1:61021   # 61000 + 21 for 10.217.79.21
```

`2333` listens on `0.0.0.0` once the server is up. `61021` is the hub service bind (`127.0.0.1`); jump SSH works only after the client is connected.

## 5. Prove jump SSH before `up`

From the Mac (no extra ProxyCommand in `~/.ssh/config` is required for
`task up`; Ansible builds the jump):

```sh
ssh -F /dev/null -o BatchMode=yes \
  -o HostKeyAlias=roaming-1 \
  -o ProxyCommand="ssh -F /dev/null -o BatchMode=yes -o HostKeyAlias=static-1 -i ~/.ssh/<project>-prod -W %h:%p ops@<static-1-public-ip>" \
  -p 61021 ops@127.0.0.1 true
```

Fix hub firewall, client unit, or token until this returns success with
key-based `ops` login.

### Checklist before `up`

| Check | OK? |
| --- | --- |
| Rathole server on `static-1` | |
| Client unit enabled on the roaming VM | |
| Hub TCP **2333** open | |
| Jump SSH to `127.0.0.1:61021` via the hub | |
| Host key fingerprint in `hosts.yml` | |

## 6. Bring-up sequence

1. Finish §1–§5.
2. If `control_plane: mac`, run `task up ENV=prod`.
   If `control_plane: gha`, commit `hosts.yml` and `group_vars/all/vault.yml` (rathole secrets from §4), then Actions → Deploy → `up`. Do not Mac-`task up` a GHA inventory. `task rathole-client-bootstrap` on a Mac is still required once so the install script exists.
   - Reconciles rathole server on the hub; refreshes roaming known_hosts through the jump.
   - Reaches roaming via mesh if already up, else via the rathole jump.
   - On roaming: reconciles the rathole **client** config, then WireGuard as today.
3. Spot-check: `task ssh ENV=prod NODE=roaming-1` (Mac control plane). GHA inventories have no Mac mesh peer; use Deploy **verify** or SSH to a static public IP.

## 7. Day-2 operations

| Event | Action |
| --- | --- |
| Roaming public IP changes | Nothing for pure roaming; keepalive refreshes mapping on static hub |
| Roaming reboot | Ensure `rathole-client` and WireGuard start on the roaming node |
| Add/remove `roaming-N` | Edit `hosts.yml` + vault keys; `up` (hub rathole server drops removed services) |
| Mac off-LAN, mesh up | `ssh` / Ansible via mesh IPs |
| Mesh down, recover roaming | Jump SSH via rathole on the static hub |
| Spoke↔spoke or Mac↔roaming fails | Confirm static `ip_forward`, FORWARD accept, dial helper |

## 8. Explicit non-goals

- Inbound WireGuard port-forward on the home router
- Using rathole as the `scwg0` (WireGuard UDP) transport
- Lima guests (Lima-local SSH only)
- Cloudflare Tunnel / `cloudflared` for roaming bootstrap
- Direct roaming↔roaming WireGuard peers (spoke↔spoke is static-relayed only)
- Rathole on every static (hub only)
- Tearing rathole down on `task down` (it is the mesh-down recovery path)
