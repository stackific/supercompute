# Roaming WireGuard nodes (dynamic IP)

This guide is the operator runbook for adding Ubuntu **26.04** amd64 machines
with a **changing public IP** (typically home lab VMs) to a **public-endpoint**
WireGuard mesh (usually operator `prod`). Stable static hosts also run Ubuntu
**26.04**, with fixed `public_ip` values.

**Lima guests (`node_lima_guest: true`, e.g. `dev-lima` `roaming-1`) do not use this
guide.** They still dial a public static WireGuard `Endpoint` (build-up hub,
then the shared roaming dial helper), but bootstrap Ansible uses **Lima-local
SSH** (not Cloudflare). Fingerprints for those guests are auto-filled by
`lima-up ENV=dev-lima` / `lima-host-fingerprints ENV=dev-lima` — see [lima.md](lima.md). Do
not set `bootstrap_ssh_host` on Lima guests.

Inventory hostnames: stable public hosts as `static-1`, `static-2`, …; roaming as
`roaming-1`, `roaming-2`, … (not `home-*` / `prod-*`).

**WireGuard rule:** roaming nodes **always initiate**. Stable peers (static
public hosts, Mac) never dial the roaming node and **must not** rely on an
inbound UDP **51830** forward on the home router. Do not use DynDNS (or any
public hostname) as a WireGuard `Endpoint` for roaming peers.

**Bootstrap SSH (non-Lima roaming only):** use **Cloudflare Tunnel**. The Mac
reaches the roaming VM over SSH through Cloudflare before (and when) the
WireGuard mesh is down. Cloudflare does **not** carry `scwg0` UDP; after join,
day-2 mesh SSH uses WireGuard addresses.

`up` syncs `.state` (known_hosts + mesh configs) from `hosts.yml`. For
non-Lima `roaming: true` it uses `bootstrap_ssh_host` (not a
public WG endpoint). Prepare the tunnel and prove SSH first, then fill inventory.
Mesh address lives on each host as `private_address`.

## 0. What you are building

- Existing **static public** nodes: Ubuntu 26.04, stable public IPs, already on the mesh.
- **Roaming** node(s): Ubuntu 26.04 amd64, dynamic public IP, same mesh
  (`scwg0` / `10.217.79.0/24` on typical prod).
- Mac controller: unchanged.
- Bootstrap path: Cloudflare Tunnel → published SSH hostname → Mac `cloudflared`
  ProxyCommand → `ops@<hostname>`.

## 1. Prerequisites

1. Prod mesh already works: `task ssh ENV=prod NODE=static-1` succeeds.
2. Operator SSH key and vault as in [setup-prod.md](setup-prod.md).
3. Domain zone on Cloudflare (same account as the tunnel), e.g. `example.com`.
4. On the roaming Ubuntu VM: `cloudflared` already installed and the tunnel
   **connected** (you already have this running).

## 2. Prepare the roaming VM (once per machine)

On the roaming VM (console or any existing SSH):

1. Ubuntu **26.04** amd64.
2. Create the same inventory user as prod (example `ops`), install the Mac
   public key, passwordless sudo — same steps as setup-prod “Prepare each
   static public host”, adapted for this host.
3. Confirm `sshd` listens on port **22** on localhost (default).
4. Confirm outbound UDP works (default on most home routers). **Do not**
   port-forward UDP 51830 inbound.
5. Confirm the tunnel is healthy:

```sh
sudo systemctl status cloudflared
# or your unit name
cloudflared tunnel list
cloudflared tunnel info <TUNNEL_NAME_OR_ID>
```

## 3. Point a hostname at the tunnel (SSH published application)

Goal: public hostname such as `roaming-1.example.com` routes through your
existing tunnel to **SSH on the same machine** as `cloudflared`.

**Prefer the dashboard (§3.1).** Skip §3.4 unless you deliberately run the
tunnel from a YAML file on the VM.

### 3.1 Add the published application (dashboard)

1. Open [Cloudflare One → Networks → Tunnels](https://one.dash.cloudflare.com/).
2. Select your running tunnel.
3. Open **Routes** (or **Published application routes**) → **Add** →
   **Published application** (wording may be **Add published application**).
4. Fill the form:

| Field | Value | Notes |
| --- | --- | --- |
| Subdomain | e.g. `ubu26-nas` or `roaming-1` | Becomes `<subdomain>.<domain>` |
| Domain | your Cloudflare zone | e.g. `example.com` |
| Path | leave empty | |
| Type / protocol | **SSH** | Not HTTP/HTTPS |
| Service / URL | `localhost:22` | **Not** bare `22`. Means sshd on this host |

If the UI wants a full URI, use `ssh://localhost:22`.

5. Leave HTTP/TLS/Connection extras on defaults unless you know you need them.
6. Click **Add route** (or **Save**).

Wrong: Service URL = `22` alone. Right: type **SSH** + `localhost:22`.

### 3.2 Confirm DNS

Cloudflare usually creates a **CNAME** for that hostname to
`<tunnel-id>.cfargotunnel.com`. In the zone’s **DNS** records, confirm the
hostname exists. If missing, add the CNAME (proxied / orange cloud is fine for
this SSH-over-Access path), or from a machine with tunnel credentials:

```sh
cloudflared tunnel route dns <TUNNEL_NAME> roaming-1.example.com
```

If you changed a local config file on the VM (§3.4), restart the agent:

```sh
sudo systemctl restart cloudflared
```

### 3.3 (Recommended) Cloudflare Access application

1. Zero Trust → **Access** → **Applications** → **Add self-hosted**.
2. Application domain: the same hostname (e.g. `roaming-1.example.com`).
3. Policy: allow your email / IdP group (add a [service token](https://developers.cloudflare.com/cloudflare-one/identity/service-tokens/) later if Ansible must be non-interactive).
4. Save.

### 3.4 Optional: same route via a file on the VM

Use this **only** if the tunnel on the roaming VM is started with a local
`config.yml` (often `/etc/cloudflared/config.yml`) instead of routes created
in the Cloudflare dashboard. Dashboard-managed tunnels do not need this file.

That file’s `ingress:` list is “when someone hits this public hostname, forward
to this local service.” For SSH bootstrap you want one rule that says:

- public name: `roaming-1.example.com`
- local target: SSH on this machine (`ssh://localhost:22`)

Cloudflare also requires a final catch-all rule so unmatched hostnames get a
404 instead of undefined behavior.

```yaml
# Fragment only — keep your existing tunnel: and credentials-file: lines.
ingress:
  - hostname: roaming-1.example.com
    service: ssh://localhost:22
  - service: http_status:404   # must be last
```

Then restart: `sudo systemctl restart cloudflared`. Prefer §3.1 if you are not
already maintaining this file.

## 4. Mac: cloudflared and SSH config

Cloudflare Tunnel SSH is **not** plain TCP to port 22. The Mac needs
`cloudflared` and a `ProxyCommand`.

`task setup` installs `cloudflared` on macOS when it is missing. Confirm:

```sh
command -v cloudflared
```

Add to `~/.ssh/config` (adjust user and key to match [setup-prod.md](setup-prod.md)):

```sshconfig
Host roaming-1.example.com
  User ops
  IdentityFile ~/.ssh/<project>-prod
  IdentitiesOnly yes
  ProxyCommand cloudflared access ssh --hostname %h
```

Example with a real hostname:

```sshconfig
Host ubu26-nas.example.com
  User ops
  IdentityFile ~/.ssh/sc-prod
  IdentitiesOnly yes
  ProxyCommand cloudflared access ssh --hostname %h
```

Also add `ubu26-desk.example.com` the same way when that roaming host exists.
## 5. Prove SSH before inventory

```sh
ssh roaming-1.example.com true
```

The first connection may open a browser for Access login. Fix Access policy or
identity until this returns success with no password prompt (key-based `ops`
login after Access).

Record the SSH **host** key fingerprint (for inventory):

```sh
ssh roaming-1.example.com 'sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub'
```

Store the full `SHA256:…` line.

### Checklist before inventory

| Check | OK? |
| --- | --- |
| Tunnel connected on the roaming VM | |
| Published route: SSH → `localhost:22` | |
| DNS CNAME for the hostname | |
| `ssh <hostname> true` from the Mac | |
| Host key fingerprint recorded | |

## 6. Inventory values

In `inventories/prod/hosts.yml`:

```yaml
roaming-1:
  roaming: true
  bootstrap_ssh_host: "roaming-1.example.com"
  ssh_ed25519_sha256: "SHA256:…"
  private_address: 10.217.79.21   # free address in 10.217.79.0/24
  # no public_ip — roaming never publishes a WG dial-in address
  # OS defaults match prod (Ubuntu 26.04 amd64); override only if a host differs
```

`bootstrap_ssh_host` must be the Cloudflare hostname from §3 (the same
name as in `~/.ssh/config`).

Add or remove `roaming-N` only in `hosts.yml`; peer configs, Vault keys,
hub `AllowedIPs`, and mesh verification all follow every host with
`roaming: true`. No template hardcoding of `roaming-1` /
`roaming-2` — a third roaming node is the same inventory pattern plus `up`.

### Day-2 path (build-up hub, then random static dial)

Roaming peers have **no stable public Endpoint**, so there is never a direct
WireGuard peer between them (or a reliable Mac→roaming dial without a known
address). Build-up pins the first static as **`static_hub`**. After WG is
up, every roaming node runs `/usr/local/sbin/supercompute-roaming-dial`, which
uses `shuf` to pick **one** public static from
`/etc/supercompute/public-endpoints.list` and `wg set` to make that peer the
active Endpoint/transit. A systemd timer (default **hourly**) re-runs so the
choice is not permanently fixed. With `node_forward_on_all_statics: true`
(dev default), every public static can forward.

| Path | After `up` |
| --- | --- |
| Mac ↔ roaming | via the static that currently holds transit AllowedIPs (Mac conf still peers roaming through the first hub) |
| roaming ↔ roaming (spoke↔spoke) | via the active dial/transit static |
| roaming ↔ a public static | direct when that static is the chosen Endpoint |

Hub selection for build-up: first non-roaming host in the static set
(`static-1` by sort order) → `static_hub`. On `up`, Ansible:

1. Enables `net.ipv4.ip_forward` (sysctl drop-in + live apply) and a FORWARD
   accept on the WG interface on the hub, and on **all** public statics when
   `node_forward_on_all_statics` is true (`wg-quick` PostUp re-adds
   iptables on boot).
2. On each roaming node, puts **Mac (if present) + every other roaming mesh
   `/32`** on the build-up hub peer’s `AllowedIPs` initially; the dial helper
   moves transit AllowedIPs to the randomly chosen static afterward.
3. On the Mac (when `control_plane: mac`), puts all roaming `/32`s on the hub
   peer the same way.
4. Runs `wg-quick strip … \| wg syncconf …` on every node whenever any
   roaming host exists — systemd `started` does **not** reload `AllowedIPs`
   when the conf file is unchanged; syncconf applies peer updates without
   dropping mesh SSH ([wg-quick(8)](https://git.zx2c4.com/wireguard-tools/about/src/man/wg-quick.8)
   strip + [wg(8)](https://git.zx2c4.com/wireguard-tools/about/src/man/wg.8)
   syncconf).
5. Installs the roaming dial helper + timer; runs it once after WG is up.
6. Proves mesh SSH for **every** peer pair, including spoke↔spoke.

**Ansible note:** SSH to `bootstrap_ssh_host` must use the Cloudflare
`ProxyCommand` (`cloudflared access ssh`). Plain SSH without `cloudflared` fails.

## 7. Provider firewall on each static public host

The roaming public IP changes. **Each dialable public static** must accept
**inbound UDP 51830** from a wide enough source set (often the public
internet), not only from a fixed list of peer `/32`s that never include the
current roaming IP. Post-build dial may choose any static, not only
`static-1`.

TCP 22 from the Mac for **static host** management stays separate from WireGuard and
from Cloudflare bootstrap to roaming.

## 8. Bring-up sequence

1. Finish §1–§6 (tunnel, Mac SSH, inventory).
2. Ensure Vault WireGuard keys include each `roaming-N`
   (`task up ENV=prod` ensures WireGuard keys in the vault).
3. `task up ENV=prod`
   - Configures static hosts + Mac (when `control_plane: mac`) with roaming
     peers (**no** Endpoint on stables toward roaming).
   - Reaches roaming via mesh if already up, else via
     `bootstrap_ssh_host` (Cloudflare Tunnel SSH).
   - On roaming: build-up `Endpoint` + `PersistentKeepalive = 25` toward the
     first hub; then dial helper may move Endpoint to another public static.
   - Syncs live peers with `wg syncconf` (see §6).
   - Installs cluster stack + `/etc/supercompute/*` in the same `up`.
   - Mesh prove must include `roaming-N` ↔ `roaming-M` via a static relay.
4. Spot-check: from Mac `task ssh ENV=prod NODE=roaming-1` (and
   `NODE=roaming-2` if present); on roaming
   `systemctl status supercompute-roaming-dial.timer`.
5. Add another roaming VM: new hostname + inventory + vault keys, then `up`.

## 9. Day-2 operations

| Event | Action |
| --- | --- |
| Roaming public IP changes | Nothing for pure roaming; keepalive refreshes mapping on static hub |
| Roaming reboot | Ensure `cloudflared` and WireGuard start on the roaming node |
| Add/remove `roaming-N` | Edit `hosts.yml` + vault keys; `up` (syncconf refreshes live `AllowedIPs`) |
| Mac off-LAN, mesh up | `ssh` / Ansible via mesh IPs |
| Mesh down, recover roaming | SSH via Cloudflare hostname (§4–§5) |
| Spoke↔spoke or Mac↔roaming fails | Confirm static `ip_forward`, FORWARD accept, dial helper (`wg show`, `supercompute-roaming-dial.timer`), and transit AllowedIPs; re-run `up` |
| Dial stuck on one static | Check `/etc/supercompute/public-endpoints.list` and timer; run `/usr/local/sbin/supercompute-roaming-dial` |

## 10. Explicit non-goals

- Inbound WireGuard port-forward or DynDNS as a WG Endpoint for roaming
- Using Cloudflare Tunnel as the `scwg0` (WireGuard UDP) transport
- LAN / Tailscale / DynDNS as documented bootstrap paths (Cloudflare only here)
- This repo installing or managing `cloudflared` on the roaming VM
- Direct roaming↔roaming WireGuard peers (spoke↔spoke is static-relayed only)
- Leaving roaming without any dialable public static (build-up and day-2 dial
  both need at least one static with a public `public_ip`)
