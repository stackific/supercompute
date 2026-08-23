# Roaming WireGuard nodes (dynamic IP)

This guide is the operator runbook for adding Ubuntu **26.04** amd64 machines
with a **changing public IP** (typically home lab VMs) to a **public-endpoint**
WireGuard mesh (usually operator `prod`). Stable static hosts also run Ubuntu
**26.04**, with fixed `cloud_wireguard_endpoint` values.

**Lima guests (`node_lima_guest: true`, e.g. `dev` `roaming-1`) do not use this
guide.** They still dial the public hub WireGuard `Endpoint`, but bootstrap
Ansible uses **Lima-local SSH** (not Cloudflare). Fingerprints for those guests
are auto-filled by `lima-up` / `lima-host-fingerprints` — see
[setup-dev.md](setup-dev.md). Do not set `cloud_bootstrap_ssh_host` on Lima
guests.

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
non-Lima `wireguard_roaming: true` it uses `cloud_bootstrap_ssh_host` (not a
public WG endpoint). Prepare the tunnel and prove SSH first, then fill inventory.
Mesh address lives on each host as `cloud_wireguard_address`.

## 0. What you are building

- Existing **static public** nodes: Ubuntu 26.04, stable public IPs, already on the mesh.
- **Roaming** node(s): Ubuntu 26.04 amd64, dynamic public IP, same mesh
  (`scwg0` / `10.217.79.0/24` on typical prod).
- Mac controller: unchanged.
- Bootstrap path: Cloudflare Tunnel → published SSH hostname → Mac `cloudflared`
  ProxyCommand → `ops@<hostname>`.

## 1. Prerequisites

1. Prod mesh already works: `task ssh PROVIDER=prod NODE=static-1` succeeds.
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
  IdentityFile ~/.ssh/<cloud_name>-prod
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
  wireguard_roaming: true
  cloud_bootstrap_ssh_host: "roaming-1.example.com"
  cloud_ssh_host_ed25519_sha256: "SHA256:…"
  cloud_wireguard_address: 10.217.79.21   # free address in 10.217.79.0/24
  # no cloud_wireguard_endpoint — roaming never publishes a WG dial-in address
  # OS defaults match prod (Ubuntu 26.04 amd64); override only if a host differs
```

`cloud_bootstrap_ssh_host` must be the Cloudflare hostname from §3 (the same
name as in `~/.ssh/config`).

Add or remove `roaming-N` only in `hosts.yml`; peer configs, Vault keys,
hub `AllowedIPs`, and mesh verification all follow every host with
`wireguard_roaming: true`. No template hardcoding of `roaming-1` /
`roaming-2` — a third roaming node is the same inventory pattern plus
`up` / `up`.

### Day-2 path (hub stays)

Roaming peers have **no stable public Endpoint**, so there is never a direct
WireGuard peer between them (or a reliable Mac→roaming dial without a known
address). The deliberate compromise: keep the first static public hub as the
**permanent relay** after bootstrap instead of DynDNS / endpoint discovery /
inbound UDP **51830** on the home router.

| Path | After `up` |
| --- | --- |
| Mac ↔ roaming | via static hub |
| roaming ↔ roaming (spoke↔spoke) | via static hub |
| roaming ↔ that static hub | direct (roaming dials `Endpoint`) |

Hub selection: first non-roaming host in the static set (`static-1` by sort
order) → `cloud_wireguard_hub`. On `up`, Ansible:

1. Enables hub `net.ipv4.ip_forward` (sysctl drop-in + live apply) and a
   FORWARD accept on the WG interface (`wg-quick` PostUp re-adds iptables on
   boot).
2. On each roaming node, puts **Mac + every other roaming mesh `/32`** on the
   hub peer’s `AllowedIPs` (cryptokey route through the hub).
3. On the Mac, puts all roaming `/32`s on the hub peer the same way.
4. Runs `wg-quick strip … \| wg syncconf …` on every node whenever any
   roaming host exists — systemd `started` does **not** reload `AllowedIPs`
   when the conf file is unchanged; syncconf applies peer updates without
   dropping mesh SSH ([wg-quick(8)](https://git.zx2c4.com/wireguard-tools/about/src/man/wg-quick.8)
   strip + [wg(8)](https://git.zx2c4.com/wireguard-tools/about/src/man/wg.8)
   syncconf).
5. Proves mesh SSH for **every** peer pair, including spoke↔spoke.

**Ansible note:** SSH to `cloud_bootstrap_ssh_host` must use the Cloudflare
`ProxyCommand` (`cloudflared access ssh`). Plain SSH without `cloudflared` fails.

## 7. Provider firewall on each static public host

The roaming public IP changes. Each static hub must accept **inbound UDP 51830** from
a wide enough source set (often the public internet), not only from a fixed
list of peer `/32`s that never include the current roaming IP.

TCP 22 from the Mac for **static host** management stays separate from WireGuard and
from Cloudflare bootstrap to roaming.

## 8. Bring-up sequence

1. Finish §1–§6 (tunnel, Mac SSH, inventory).
2. Ensure Vault WireGuard keys include each `roaming-N`
   (`task vault-wireguard-ensure PROVIDER=prod` or via `up`).
3. `task up PROVIDER=prod`
   - Configures static hosts + Mac with roaming peer (**no** Endpoint on stables).
   - Reaches roaming via mesh if already up, else via
     `cloud_bootstrap_ssh_host` (Cloudflare Tunnel SSH).
   - On roaming: WireGuard with `Endpoint` + `PersistentKeepalive = 25` toward
     each static hub; hub peer `AllowedIPs` include Mac + other roaming `/32`s.
   - Syncs live peers with `wg syncconf` (see §6).
   - Mesh prove must include `roaming-N` ↔ `roaming-M` via the hub.
4. Spot-check: from Mac `task ssh PROVIDER=prod NODE=roaming-1` (and
   `NODE=roaming-2` if present).
5. Optional cluster stack: `task up PROVIDER=prod` (see
   [setup-prod.md](setup-prod.md) — gVisor, Docker Engine, Caddy, and PowerDNS).
6. Add another roaming VM: new hostname + inventory + vault keys, then
   `up` (and `task up PROVIDER=prod` if you want node packages).

## 9. Day-2 operations

| Event | Action |
| --- | --- |
| Roaming public IP changes | Nothing for pure roaming; keepalive refreshes mapping on static hub |
| Roaming reboot | Ensure `cloudflared` and WireGuard start on the roaming node |
| Add/remove `roaming-N` | Edit `hosts.yml` + vault keys; `up` (syncconf refreshes live `AllowedIPs`) |
| Mac off-LAN, mesh up | `ssh` / Ansible via mesh IPs |
| Mesh down, recover roaming | SSH via Cloudflare hostname (§4–§5) |
| Spoke↔spoke or Mac↔roaming fails | Confirm hub `ip_forward`, FORWARD accept, and hub peer `AllowedIPs` on the roaming node (`wg show`); re-run `up` |

## 10. Explicit non-goals

- Inbound WireGuard port-forward or DynDNS as a WG Endpoint for roaming
- Using Cloudflare Tunnel as the `scwg0` (WireGuard UDP) transport
- LAN / Tailscale / DynDNS as documented bootstrap paths (Cloudflare only here)
- This repo installing or managing `cloudflared` on the roaming VM
- Direct roaming↔roaming WireGuard peers (spoke↔spoke is hub-relayed only)
- Dropping the static hub after bootstrap without endpoint discovery or another
  relay (pure WireGuard cannot dial unknown roaming public IPs)
