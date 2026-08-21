# Roaming WireGuard nodes (dynamic IP)

This guide is the operator runbook for adding Ubuntu **26.04** amd64 machines
with a **changing public IP** (typically home lab VMs) to the production
WireGuard mesh. Stable **prod** VPS nodes also run Ubuntu **26.04**, with fixed
`prod_wireguard_endpoint` values.

Inventory hostnames: stable VPS as `static-1`, `static-2`, …; roaming as
`roaming-1`, `roaming-2`, … (not `home-*` / `prod-*`).

**WireGuard rule:** roaming nodes **always initiate**. Stable peers (VPS, Mac)
never dial the roaming node and **must not** rely on an inbound UDP **51830**
forward on the home router. Do not use DynDNS (or any public hostname) as a
WireGuard `Endpoint` for roaming peers.

**Bootstrap SSH:** this project uses **Cloudflare Tunnel** only. The Mac reaches
the roaming VM over SSH through Cloudflare before (and when) the WireGuard mesh
is down. Cloudflare does **not** carry `scwg0` UDP; after join, day-2 mesh SSH
uses WireGuard addresses.

`wg-up` syncs `.state` (known_hosts + mesh configs) from `hosts.yml`. For
`wireguard_roaming: true` it uses `prod_bootstrap_ssh_host` (not a public WG
endpoint). Prepare the tunnel and prove SSH first, then fill inventory. Mesh
address lives on each host as `prod_wireguard_address`.

## 0. What you are building

- Existing **prod VPS** nodes: Ubuntu 26.04, stable public IPs, already on the mesh.
- **Roaming** node(s): Ubuntu 26.04 amd64, dynamic public IP, same mesh
  (`scwg0` / `10.217.79.0/24`).
- Mac controller: unchanged.
- Bootstrap path: Cloudflare Tunnel → published SSH hostname → Mac `cloudflared`
  ProxyCommand → `ops@<hostname>`.

## 1. Prerequisites

1. Prod mesh already works: `task wg-ssh PROVIDER=prod NODE=static-1` succeeds.
2. Operator SSH key and vault as in [setup-prod.md](setup-prod.md).
3. Domain zone on Cloudflare (same account as the tunnel), e.g. `example.com`.
4. On the roaming Ubuntu VM: `cloudflared` already installed and the tunnel
   **connected** (you already have this running).

## 2. Prepare the roaming VM (once per machine)

On the roaming VM (console or any existing SSH):

1. Ubuntu **26.04** amd64.
2. Create the same inventory user as prod (example `ops`), install the Mac
   public key, passwordless sudo — same steps as setup-prod “Prepare each
   VPS”, adapted for this host.
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
| Subdomain | e.g. `roaming-1` or `qnap-ubu26` | Becomes `<subdomain>.<domain>` |
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
  IdentityFile ~/.ssh/<deployment_name>-prod
  IdentitiesOnly yes
  ProxyCommand cloudflared access ssh --hostname %h
```

Example with a real hostname:

```sshconfig
Host qnap-ubu26.tanzimsaqib.com
  User ops
  IdentityFile ~/.ssh/templ-cluster-prod
  IdentitiesOnly yes
  ProxyCommand cloudflared access ssh --hostname %h
```

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
  prod_bootstrap_ssh_host: "roaming-1.example.com"
  prod_ssh_host_ed25519_sha256: "SHA256:…"
  prod_wireguard_address: 10.217.79.21   # free address in 10.217.79.0/24
  # no prod_wireguard_endpoint — roaming never publishes a WG dial-in address
  # OS defaults match prod (Ubuntu 26.04 amd64); override only if a host differs
```

`prod_bootstrap_ssh_host` must be the Cloudflare hostname from §3 (the same
name as in `~/.ssh/config`).

Add or remove `roaming-N` only in `hosts.yml`; peer configs and Vault keys
follow that host set on the next `wg-up`.

**Mac↔roaming mesh:** traffic goes through the first static VPS hub (`static-1`
by sort order). Roaming dials the hub; the Mac dials the hub with roaming
`AllowedIPs` included. No inbound UDP on the Mac is required. On `wg-up`,
Ansible enables hub `net.ipv4.ip_forward` (persistent drop-in + live apply)
and the WireGuard FORWARD accept rule; `wg-quick` PostUp only re-adds the
iptables rule on boot.

**Ansible note:** SSH to `prod_bootstrap_ssh_host` must use the Cloudflare
`ProxyCommand` (`cloudflared access ssh`). Plain SSH without `cloudflared` fails.

## 7. Provider firewall on each VPS

The roaming public IP changes. Each VPS must accept **inbound UDP 51830** from
a wide enough source set (often the public internet), not only from a fixed
list of peer `/32`s that never include the current roaming IP.

TCP 22 from the Mac for **VPS** management stays separate from WireGuard and
from Cloudflare bootstrap to roaming.

## 8. Intended bring-up sequence (when automation supports roaming)

1. Finish §1–§6 (tunnel, Mac SSH, inventory).
2. Ensure Vault WireGuard keys include each `roaming-N`
   (`task vault-wireguard-ensure PROVIDER=prod` or via `wg-up`).
3. `task wg-up PROVIDER=prod`
   - Configures VPS + Mac with roaming peer (**no** Endpoint on stables).
   - Reaches roaming via mesh if already up, else via
     `prod_bootstrap_ssh_host` (Cloudflare Tunnel SSH).
   - On roaming: WireGuard with `Endpoint` + `PersistentKeepalive = 25` toward
     each stable VPS.
4. Prove: from roaming `ping -I scwg0 10.217.79.1` and a VPS mesh IP; from Mac
   `task wg-ssh PROVIDER=prod NODE=roaming-1`.
5. Add/remove further roaming VMs by repeating this guide with a new hostname
   and re-running `wg-up`.

## 9. Day-2 operations

| Event | Action |
| --- | --- |
| Roaming public IP changes | Nothing for pure roaming; keepalive refreshes mapping on VPS |
| Roaming reboot | Ensure `cloudflared` and WireGuard start on the roaming node |
| Mac off-LAN, mesh up | `wg-ssh` / Ansible via mesh IPs |
| Mesh down, recover roaming | SSH via Cloudflare hostname (§4–§5) |

## 10. Explicit non-goals

- Inbound WireGuard port-forward or DynDNS as a WG Endpoint for roaming
- Using Cloudflare Tunnel as the `scwg0` (WireGuard UDP) transport
- LAN / Tailscale / DynDNS as documented bootstrap paths (Cloudflare only here)
- This repo installing or managing `cloudflared` on the roaming VM
- Roaming↔roaming relay through a VPS hub (v1)
