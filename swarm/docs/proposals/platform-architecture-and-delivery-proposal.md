# Supercompute Dynamic Application Platform
## Architecture, C4 Model, Stack, Components, Milestones, Goals, and Tasks

**Status:** Recommended production architecture  
**Audience:** Platform engineering, operations, security, product, and self-hosting customers  
**Last reviewed:** 2026-08-16  
**Scope:** Hosted SaaS and provider-neutral self-hosted deployment on a three-node k0s cluster

---

## 1. Executive decision

Build the product as a Kubernetes platform that runs OCI container images. Use Docker or BuildKit in CI to build images, but use the containerd runtime included with k0s on cluster nodes. Do not create a unique published host port for every application.

The routing model is:

```text
public TCP 80/443 on every node
        |
        v
Traefik DaemonSet, one pod per node
        |
        v
Gateway API HTTPRoute, or a narrowly scoped TLS route adapter
        |
        v
Kubernetes ClusterIP Service :8080
        |
        v
one or more application Pods listening on :8080
```

Every application may listen on internal port `8080` because each Service has its own virtual IP and DNS name. The edge proxy resolves the Service and sends traffic through the cluster network. There is no collision between applications and no need for per-application `NodePort`, `hostPort`, or host-level port allocation.

Use three combined k0s controller/worker nodes for the initial product. This is a pragmatic small-cluster topology, but its availability boundary must be stated honestly:

- Three embedded-etcd members tolerate one unavailable member while retaining quorum.
- Two unavailable members remove etcd quorum and prevent control-plane writes.
- Existing application traffic may continue for a time, but the cluster cannot safely schedule, reschedule, or reconcile without quorum.
- A highly available application normally needs at least two replicas, topology spreading, readiness probes, and a PodDisruptionBudget. A one-replica application is not highly available even when the cluster is.

Run all Kubernetes control-plane, etcd, kubelet, CNI, and inter-node traffic over the existing WireGuard network. Expose only the public application edge (`80/443`), the WireGuard UDP port, and a tightly restricted administration path.

Use these edge/TLS profiles:

1. **Platform wildcard:** cert-manager DNS-01 with a narrow Cloudflare token for `*.templ-prod.supercompute.dev`.
2. **SaaS custom domains:** Cloudflare for SaaS terminates each customer certificate and forwards to a stable, health-checked origin.
3. **Provider-neutral self-hosted domains:** cert-manager HTTP-01 through Gateway API for exact hostnames; DNS-01 or BYO certificates for wildcards.
4. **Large direct-certificate fleets:** retain Gateway API for normal routing, but use a per-route Traefik TLS adapter when a single Gateway listener becomes an unsafe certificate aggregation point.
5. **Local development:** `sslip.io` hostnames plus a static `mkcert` wildcard secret, with the same application labels and route model.

The only intended environment-specific differences are values such as domain suffix, public endpoint mode, certificate source, issuer, and route adapter. Application Deployments and Services remain the same.

---

## 2. Goals and non-goals

### 2.1 Goals

- Dynamically provision and remove applications without allocating unique host ports.
- Route by hostname to applications that all expose port `8080` internally.
- Keep the same desired-state structure for SaaS, self-hosted, and local development.
- Provide a viable three-node launch architecture without pretending it has unlimited fault tolerance.
- Support gVisor selectively for workloads that benefit from an additional userspace-kernel isolation boundary.
- Support a platform wildcard, customer domains, and self-hosted DNS providers without making Cloudflare or AWS mandatory for the product.
- Make provisioning idempotent and observable: an application is not “ready” until workload, route, TLS, and an external HTTPS check all succeed.
- Keep infrastructure reproducible with Ansible and k0sctl; use Ansible Vault for bootstrap and installer secrets.
- Establish clear upgrade, backup, restore, and support boundaries suitable for a commercial product.

### 2.2 Non-goals for the first production release

- Building a general-purpose public cloud or a replacement for every managed Kubernetes feature.
- Running arbitrary privileged containers for ordinary tenants.
- Offering persistent distributed block storage before backup, repair, and restore operations are proven.
- Creating a custom Kubernetes operator merely to appear “cloud native.” Start with an idempotent reconciler using the Kubernetes API; add CRDs only when they create a real contract or delegation benefit.
- Exposing the Kubernetes API, etcd, kubelet, Traefik dashboard, or internal metrics to the public internet.
- Guaranteeing availability when two of three nodes, the WireGuard mesh, or the upstream DNS/load-balancing provider fails.
- Treating DNS round-robin as health-aware failover.

---

## 3. Terminology

| Term | Meaning in this design |
|---|---|
| **Application** | A customer-created workload consisting of a Deployment, Service, route, policy, and optional certificate/domain binding. |
| **Platform controller** | The product service that reconciles database desired state into Kubernetes resources and external provider resources. It is not necessarily a Kubernetes CRD operator in version 1. |
| **Edge** | Traefik instances running on all three nodes and binding public TCP `80/443`. |
| **Platform hostname** | A hostname below the platform wildcard, such as `clever-fox-21.templ-prod.supercompute.dev`. |
| **Custom hostname** | A customer-owned hostname, such as `app.customer.com`. |
| **Direct custom-domain mode** | The customer’s DNS points directly to the self-hosted or SaaS origin, and the cluster terminates the customer certificate. |
| **Cloudflare for SaaS mode** | Cloudflare terminates the customer certificate, validates the hostname, and forwards to the platform fallback origin. |
| **Route adapter** | An implementation layer that converts one platform RouteBinding object into Gateway API `HTTPRoute`, Traefik `IngressRoute`, or another supported edge resource. |
| **Isolation profile** | A product-level choice such as `standard` or `gvisor`, translated into pod security and `runtimeClassName`. |

---

## 4. Architectural decisions at a glance

| Area | Recommended decision | Why |
|---|---|---|
| Orchestrator | k0s Kubernetes | Compact distribution, embedded containerd, good Ansible/k0sctl fit, HA controllers, and RuntimeClass support. |
| Node role | Three `controller+worker` nodes with `noTaints: true` | Makes full use of three machines at launch. Reserve resources so workloads cannot starve the control plane. |
| Datastore | Embedded etcd on all three nodes | Standard odd-member quorum. One-node failure tolerance. |
| Inter-node network | Existing WireGuard underlay | Keeps management and node traffic private and encrypted. |
| CNI | Calico VXLAN over WireGuard; Calico WireGuard disabled | Provides Kubernetes NetworkPolicy and avoids adding a second encryption layer. |
| Edge proxy | Traefik v3 from the official Helm chart | Gateway API support, DaemonSet/hostPort deployment, TLS options, and a practical CRD escape hatch for direct per-route TLS. |
| Kubernetes routing API | Gateway API `Gateway` + `HTTPRoute` | Current Kubernetes direction; clear separation between infrastructure-owned listeners and application-owned routes. |
| Public bind | Traefik DaemonSet with `hostPort: 80/443` | Every DNS-listed node accepts traffic without a cloud `LoadBalancer` Service. Prefer this to `hostNetwork`. |
| Workload exposure | ClusterIP Service, port `8080` | No port collisions and no public per-app ports. |
| SaaS platform TLS | cert-manager DNS-01 wildcard | Wildcards require DNS validation; automatic renewal. |
| SaaS custom-domain TLS | Cloudflare for SaaS | Scales customer certificates outside the Kubernetes listener and supports prevalidation and health-aware origins. |
| Self-host exact-host TLS | cert-manager HTTP-01 through Gateway API | DNS-provider-neutral and only requires public `80/443`. |
| Self-host wildcard TLS | DNS-01, delegated ACME challenge, RFC2136/webhook, or BYO certificate | HTTP-01 cannot issue wildcard certificates. |
| Local TLS | `mkcert` static secret | Trusted local CA and wildcard support; development only. |
| Sandbox runtime | gVisor `runsc` RuntimeClass, opt-in | Adds workload isolation while preserving normal `runc` compatibility for unsupported applications. |
| Provisioning | Product reconciler + Kubernetes server-side apply | Idempotent and simple to operate; no mandatory custom operator initially. |
| Secrets | Ansible Vault for bootstrap; Kubernetes Secrets encrypted at rest | Keeps installer secrets out of Git and protects cluster-stored secrets. |
| Persistent data | External managed DB/object storage first; CSI module later | Avoids turning distributed storage into the first operational bottleneck. |

---

## 5. C4 architecture

### 5.1 C4 Level 1 — System context

```text
+----------------------+                         +-----------------------+
| SaaS customer/admin  |                         | Self-hosted operator  |
| browser / API client |                         | browser / API client  |
+----------+-----------+                         +-----------+-----------+
           | HTTPS                                               | HTTPS
           v                                                     v
+--------------------------------------------------------------------------+
|                 Supercompute Application Platform                        |
|                                                                          |
|  Creates isolated application workloads, binds domains and TLS, routes   |
|  traffic, monitors readiness, and manages the application lifecycle.     |
+----------------------+-------------------------+-------------------------+
                       |                         |
          SaaS adapter |                         | Self-host adapters
                       v                         v
          +-----------------------+    +-------------------------------+
          | Cloudflare APIs       |    | Customer DNS / ACME / BYO TLS |
          | DNS, LB, SaaS domains |    | Any compatible DNS provider   |
          +-----------------------+    +-------------------------------+
                       |
                       v
          +-----------------------+
          | OCI image registry    |
          | pinned application    |
          | and platform images   |
          +-----------------------+
```

### 5.2 C4 Level 2 — Containers: hosted SaaS

```text
 Internet users
       |
       | app.customer.com or *.templ-prod.supercompute.dev
       v
+------------------------------- Cloudflare --------------------------------+
|  DNS / Cloudflare for SaaS / optional health-aware load-balancing          |
|  - customer edge certificate                                               |
|  - hostname ownership validation                                           |
|  - WAF/rate limiting where purchased                                       |
|  - fallback origin: origin.templ-prod.supercompute.dev                     |
+---------------------------+--------------------+----------------------------+
                            |                    |
                     HTTPS origin traffic, preserved Host header
                            |
     +----------------------+----------------------+----------------------+
     |                      |                      |                      |
     v                      v                      v                      |
+-----------+          +-----------+          +-----------+             |
| node-1    |          | node-2    |          | node-3    |             |
| public IP |          | public IP |          | public IP |             |
| wg IP     |<========>| wg IP     |<========>| wg IP     |             |
+-----+-----+ WireGuard+-----+-----+ WireGuard+-----+-----+             |
      |                      |                      |                   |
      | Traefik :80/:443     | Traefik :80/:443     | Traefik :80/:443 |
      +----------------------+----------------------+-------------------+
                            |
                            v
                 +------------------------+
                 | Gateway / HTTPRoutes   |
                 +-----------+------------+
                             |
                  Kubernetes Service :8080
                             |
                    +--------+--------+
                    | application Pods|
                    | runc or gVisor   |
                    +-----------------+

Control plane on all three nodes:
  k0s controller + worker, kube-apiserver, scheduler, controller-manager,
  embedded etcd member, containerd, kubelet, Calico, CoreDNS.

Platform services:
  API/UI, reconciler, metadata database, job/queue mechanism, registry adapter,
  domain/TLS adapters, metrics/logging/alerting.
```

### 5.3 C4 Level 2 — Containers: self-hosted product

```text
 Customer users
       |
       | customer-managed DNS
       v
+------------------ customer-selected public endpoint ------------------+
| A/AAAA records, CNAME, external L4 load balancer, reverse proxy, or     |
| simple multi-A records. Cloudflare/AWS are optional, not prerequisites. |
+-------------------------------+-----------------------------------------+
                                |
          +---------------------+---------------------+
          |                     |                     |
          v                     v                     v
     +---------+           +---------+           +---------+
     | node-1  |           | node-2  |           | node-3  |
     | Traefik |           | Traefik |           | Traefik |
     +----+----+           +----+----+           +----+----+
          +---------------------+---------------------+
                                |
                     Gateway API / route adapter
                                |
                     Service :8080 -> Pods

+------------------------------------------------------------------------+
| Self-hosted management plane                                           |
| - platform API/UI and reconciler                                       |
| - local/customer database                                              |
| - cert-manager HTTP-01, optional DNS-01, private CA, or BYO TLS        |
| - no mandatory call to Supercompute or Cloudflare                      |
+------------------------------------------------------------------------+
```

### 5.4 C4 Level 3 — Dynamic provisioning components

```text
+------------------------+
| Product API / UI       |
| POST /applications     |
+-----------+------------+
            |
            v
+------------------------+       +-------------------------+
| Metadata database      |<----->| Reconciliation queue    |
| desired state, domain  |       | retries and idempotency |
| ownership, status      |       +-----------+-------------+
+------------------------+                   |
                                             v
                                +---------------------------+
                                | Platform reconciler       |
                                |                           |
                                | 1. validate desired state |
                                | 2. reserve hostname       |
                                | 3. reconcile namespace    |
                                | 4. reconcile workload     |
                                | 5. reconcile Service      |
                                | 6. reconcile route        |
                                | 7. reconcile TLS/domain   |
                                | 8. inspect conditions     |
                                | 9. synthetic HTTPS test   |
                                +------+---------+----------+
                                       |         |
                        Kubernetes API |         | Provider adapters
                                       v         v
                         +----------------+  +----------------------+
                         | k0s cluster    |  | Cloudflare / DNS /   |
                         | resources      |  | ACME / registry      |
                         +----------------+  +----------------------+
```

### 5.5 C4 Level 3 — Edge routing components

```text
Client TLS ClientHello (SNI = clever-fox-21.templ-prod.supercompute.dev)
                               |
                               v
+----------------------------------------------------------------+
| Traefik on the selected public node                            |
|                                                                |
|  EntryPoint websecure :443                                     |
|  - select certificate using SNI                                |
|  - enforce TLS policy                                          |
|  - parse HTTP Host header                                      |
|  - match accepted HTTPRoute/IngressRoute                       |
|  - emit access log and metrics                                 |
+-----------------------------+----------------------------------+
                              |
                              v
+----------------------------------------------------------------+
| HTTPRoute                                                        |
| hostnames: [clever-fox-21.templ-prod.supercompute.dev]          |
| backendRefs: clever-fox-21, port 8080                           |
+-----------------------------+----------------------------------+
                              |
                              v
+----------------------------------------------------------------+
| ClusterIP Service clever-fox-21:8080                            |
| selector: app-id=...                                            |
+-----------------------------+----------------------------------+
                              |
                +-------------+-------------+
                |                           |
                v                           v
       Pod A 10.x.y.z:8080         Pod B 10.x.y.z:8080
       node-1, ready               node-3, ready
```

---

## 6. Request and provisioning flows

### 6.1 Platform-owned hostname

Example: `clever-fox-21.templ-prod.supercompute.dev`

```text
1. Customer creates application.
2. Platform reserves slug `clever-fox-21` using a database unique constraint.
3. Reconciler creates namespace policies, Deployment, Service and HTTPRoute.
4. Existing wildcard DNS resolves the hostname to the public edge endpoints.
5. Existing wildcard certificate covers the hostname.
6. Client reaches one edge node on 443.
7. Traefik selects the wildcard certificate from SNI.
8. HTTPRoute matches the Host header and forwards to Service port 8080.
9. Service selects only ready Pods, possibly on another node over WireGuard/CNI.
10. Platform marks the application ready only after route conditions and a
    synthetic external HTTPS request succeed.
```

No DNS mutation or per-application certificate issuance is needed for this path. It should be the fastest and most reliable onboarding path.

### 6.2 SaaS customer-owned hostname through Cloudflare for SaaS

Example: `app.customer.com`

```text
1. Customer enters app.customer.com in the platform.
2. Platform verifies the hostname is not already claimed.
3. Cloudflare adapter creates a custom hostname.
4. Platform returns the required validation/CNAME instructions.
5. Prefer prevalidation before traffic cutover where the selected plan permits it.
6. Customer creates:
      app.customer.com CNAME customers.templ-prod.supercompute.dev
7. Platform waits for both hostname status and certificate status to be active.
8. Cloudflare terminates the browser TLS session.
9. Cloudflare selects a healthy origin and connects with Full (strict) TLS.
10. Origin receives the original Host header `app.customer.com`.
11. HTTPRoute matches that Host header and sends traffic to the application.
12. Platform performs an end-to-end HTTPS probe and then marks the domain active.
```

Important consequences:

- An ordinary proxied CNAME between unrelated Cloudflare accounts is not a substitute for Cloudflare for SaaS and can fail with cross-account restrictions.
- Keep a stable fallback-origin hostname and origin certificate separate from customer hostname issuance.
- Cloudflare is an optional SaaS edge adapter. The core self-hosted product does not depend on it.

### 6.3 Provider-neutral direct custom hostname

```text
1. Customer/operator configures A/AAAA/CNAME to the deployment endpoint.
2. Platform creates a Certificate in the protected `edge-system` namespace.
3. cert-manager creates a temporary HTTPRoute for `/.well-known/acme-challenge/`.
4. The public HTTP listener on port 80 serves the challenge.
5. ACME issuer creates the exact-host certificate.
6. The route adapter attaches the TLS secret to the edge configuration.
7. Platform creates/accepts the application route.
8. Platform verifies certificate Ready, route Accepted/ResolvedRefs, and HTTPS.
```

This requires no DNS API and works with any authoritative DNS provider, but the hostname must already resolve to the deployment and port 80 must be reachable during validation.

For wildcard customer certificates, use DNS-01 through a supported cert-manager provider/webhook, RFC2136, delegated `_acme-challenge` CNAME, or a customer-supplied certificate. HTTP-01 cannot issue wildcard certificates.

### 6.4 Local development

Example: `clever-fox-21.127-0-0-1.sslip.io`

```text
1. sslip.io resolves the embedded IP to 127.0.0.1.
2. mkcert issues a locally trusted certificate for:
      127-0-0-1.sslip.io
      *.127-0-0-1.sslip.io
3. The certificate is stored as the same Kubernetes TLS Secret shape used in production.
4. The local Gateway listener and HTTPRoute objects have the same structure.
5. Application Deployment and Service still use port 8080.
```

`sslip.io` is providing DNS convenience, not a public wildcard certificate. The local trusted certificate comes from `mkcert` and must never be reused in production.

---

## 7. Deployment topology and availability

### 7.1 Three-node topology

```text
                         Public DNS / LB
                    +---------+---------+
                    |         |         |
                    v         v         v
              public IP1 public IP2 public IP3
                    |         |         |
           +--------+--+ +----+------+ +--+--------+
           | node-1    | | node-2    | | node-3    |
           |-----------| |-----------| |-----------|
           | Traefik   | | Traefik   | | Traefik   |
           | k0s ctrl  | | k0s ctrl  | | k0s ctrl  |
           | etcd #1   | | etcd #2   | | etcd #3   |
           | kubelet   | | kubelet   | | kubelet   |
           | containerd| | containerd| | containerd|
           | Calico    | | Calico    | | Calico    |
           +-----+-----+ +-----+-----+ +-----+-----+
                 \============|============/
                        WireGuard mesh
```

### 7.2 Failure behavior

| Failure | Expected behavior | Required mitigation |
|---|---|---|
| One application Pod fails | Service removes it after readiness failure. | At least two replicas for HA; correct probes. |
| One edge Pod fails | Public node may still accept TCP but not serve correctly until pod returns. | DaemonSet readiness; external LB health check; alert. |
| One node fails | etcd quorum remains; workloads reschedule if capacity exists. | Health-aware public LB, replicas spread across nodes, spare capacity. |
| One node fails with plain multi-A DNS | Some clients continue to select the dead IP until resolver/client behavior changes. | Prefer Cloudflare LB or another health-aware L4/L7 endpoint for paid SaaS. |
| Two nodes fail | etcd loses quorum; only surviving processes may continue. | Declare this outside launch SLO; restore node/quorum rather than forcing unsafe writes. |
| WireGuard partition | Depending on partition, etcd and cross-node data traffic fail. | Monitor handshake age and packet loss; avoid overlapping routes; test partitions. |
| DNS provider outage | New lookups or changes may fail. | Reasonable TTLs, provider status monitoring, documented dependency. |
| Certificate renewal failure | Existing cert works until expiry, then TLS fails. | Alerts at 30/14/7 days and staged renewal tests. |

### 7.3 Public endpoint choices

#### Profile A — Plain multi-A records

```text
*.templ-prod.supercompute.dev A node-1-public-ip
*.templ-prod.supercompute.dev A node-2-public-ip
*.templ-prod.supercompute.dev A node-3-public-ip
```

Use only as the low-cost baseline. It distributes answers but is not a reliable health-aware load balancer. TTL reduction does not force every resolver or client to immediately stop using a failed address.

#### Profile B — Cloudflare Load Balancing for hosted SaaS

Use a health monitor, one origin per node, a pool, and a proxied fallback-origin hostname. This is the recommended business-facing SaaS profile because failed origins can be removed from rotation.

#### Profile C — Customer-selected self-hosted endpoint

Support any of:

- customer L4 load balancer with TCP health checks;
- an existing reverse proxy or firewall VIP;
- BGP/MetalLB in an appropriate private environment;
- multi-A/AAAA records with the documented degradation;
- a single public IP with NAT to one or more edge nodes.

Do not encode Cloudflare-specific assumptions in the Kubernetes workload model.

---

## 8. Kubernetes and k0s design

### 8.1 k0s role model

Use `controller+worker` on all three nodes and set `noTaints: true`. Do not use `--single`; it changes datastore and lifecycle assumptions. Pin a supported k0s release in Ansible inventory instead of tracking `head`, `latest`, or an alpha release.

Use k0sctl as the production bootstrap/upgrade mechanism, invoked by Ansible. Explicitly set each node’s `privateAddress` to its WireGuard IP. k0sctl uses the private address for node and control-plane addressing; still verify the generated configuration with `k0sctl apply --dry-run` because multi-homed hosts are a common source of wrong-interface selection.

Enable k0s node-local load balancing with Envoy. This improves worker-to-control-plane resilience without requiring an external API load balancer. It does not make `kubectl` access externally highly available; operators can use a WireGuard-only HAProxy/VIP later if a stable management endpoint is required.

### 8.2 Control-plane traffic

Bind or firewall these services to the WireGuard interface/network:

- Kubernetes API: TCP `6443`
- etcd peer: TCP `2380`
- Konnectivity agent: TCP `8132`
- k0s controller join API: TCP `9443`
- kubelet API: TCP `10250`
- Calico VXLAN: UDP `4789`

The public interfaces should not accept these ports. Host firewalls remain necessary even when k0s is configured with private addresses.

### 8.3 CNI over WireGuard

Use Calico in VXLAN mode because NetworkPolicy is a product requirement. Force Calico node address detection to `wg0` or the configured WireGuard interface. Keep Calico’s own WireGuard encryption disabled; the underlay is already encrypted.

Choose MTU empirically. A reasonable starting point is the WireGuard interface MTU minus the Calico VXLAN overhead, for example `1420 - 50 = 1370`, but this is not a universal constant. Validate with path-MTU tests, large HTTP responses, cross-node traffic, and `DF` pings. Record the proven value as an environment variable.

The CNI provider is a rebuild-level choice in k0s, so decide and test it before customer data exists.

### 8.4 Resource protection on combined nodes

Combined nodes are economical but allow tenant workloads to compete with etcd, API server, containerd, CNI, and edge processes. Before production:

- reserve CPU and memory for the OS and Kubernetes system daemons;
- set eviction thresholds and disk alerts;
- give edge and critical platform services a high PriorityClass;
- apply ResourceQuota and LimitRange to tenant namespaces;
- reject workloads without requests and limits;
- keep enough free capacity to survive one node loss;
- do not schedule unrestricted build jobs or image compilation on these nodes.

A practical launch rule is to sell no more than roughly 50–60% of aggregate allocatable CPU/memory until one-node-loss tests prove the actual safe oversubscription envelope.

---

## 9. Edge routing design

### 9.1 Why Gateway API

Kubernetes recommends Gateway API for new HTTP routing work; the older Ingress API is frozen. Gateway API also fits the product’s ownership model:

- platform operators own `GatewayClass`, `Gateway`, listeners, TLS policy, and public ports;
- the application reconciler owns namespaced `HTTPRoute` resources;
- route status exposes `Accepted`, `ResolvedRefs`, and related conditions.

### 9.2 Traefik deployment

Run the official Traefik Helm chart as a DaemonSet. Bind container and host ports `80` and `443`; grant only `NET_BIND_SERVICE`, run non-root, drop all other capabilities, and avoid `hostNetwork` unless a tested platform constraint makes it unavoidable.

Do not expose the dashboard/API publicly. Use `kubectl port-forward` or a private, authenticated WireGuard-only route for troubleshooting.

### 9.3 Listener model

Use one public HTTP listener and one public HTTPS listener:

```text
listener http  :80   -> ACME HTTP-01 plus redirect to HTTPS
listener https :443  -> all approved host routes; strict SNI
```

The HTTPS listener has no fixed hostname so it can accept both the platform wildcard and approved custom hostnames. Store edge TLS Secrets in the protected `edge-system` namespace. Application routes remain in tenant namespaces and attach only when the namespace carries an explicit route-access label.

### 9.4 The customer-certificate scaling limit

Gateway API terminates TLS at the listener. `HTTPRoute` does not own its own TLS certificate. A listener allows at most 64 `certificateRefs`; only one Secret reference is a Core-supported behavior and multiple references are implementation-specific.

Therefore use these rules:

- The platform wildcard and stable SaaS origin certificate are always attached to the Gateway.
- Cloudflare for SaaS customer certificates stay at Cloudflare and do not consume Gateway certificate references.
- Small self-hosted direct-TLS installations may attach validated customer Secrets to the listener, but cap the product at **50** active direct certificate references to leave operational headroom.
- Never attach a certificate until it is `Ready`; one bad reference can invalidate or degrade a listener depending on implementation behavior.
- Above the threshold, switch the self-hosted `edge_route_provider` to `traefik-crd`, where each `IngressRoute` references its own `tls.secretName`, or shard Gateways after tested implementation-specific validation.
- Consider Gateway API `ListenerSet` only after the pinned Traefik version explicitly supports it and passes the product compatibility suite. Do not make an unverified future feature a launch dependency.

This is the one intentional abstraction leak in the edge layer. The product-level `RouteBinding` remains the same; only its rendered Kubernetes resource changes.

---

## 10. TLS and certificate architecture

### 10.1 Mode matrix

| Mode | Public certificate terminates at | Validation | DNS-provider requirement | Recommended use |
|---|---|---|---|---|
| Platform wildcard | Traefik | cert-manager DNS-01 | Cloudflare only for the platform-owned zone | Default application hostname. |
| SaaS custom hostname | Cloudflare edge | Cloudflare hostname + certificate validation | Customer may keep any authoritative DNS; usually adds a CNAME | Hosted SaaS at scale. |
| Direct exact hostname | Traefik | cert-manager HTTP-01 | None beyond ability to point DNS | Provider-neutral self-host. |
| Direct wildcard hostname | Traefik | cert-manager DNS-01 | Supported provider/webhook/RFC2136/delegation | Self-host tenant wildcard. |
| BYO TLS | Traefik | Operator imports Secret | None | Air-gapped/private PKI/customer policy. |
| Local | Traefik | `mkcert` | `sslip.io` for name resolution | Developer workstation/CI lab. |

### 10.2 Platform wildcard

Issue a Certificate with both the wildcard and apex/fallback names actually needed:

```text
*.templ-prod.supercompute.dev
origin.templ-prod.supercompute.dev
```

A wildcard does not cover the zone apex itself. Keep the Cloudflare API token in a Kubernetes Secret created from Ansible Vault. Give it only zone read and DNS edit permissions for the required zone.

### 10.3 Hosted SaaS custom domains

Use Cloudflare for SaaS rather than attempting to put thousands of customer private keys into one cluster listener. Configure:

- `customers.templ-prod.supercompute.dev` as the customer-facing CNAME target;
- `origin.templ-prod.supercompute.dev` as the fallback-origin hostname;
- a Cloudflare LB pool with all three node origins and a `/healthz/edge` monitor;
- origin encryption mode Full (strict);
- a certificate on the origin that matches the configured origin SNI/target hostname;
- hostname prevalidation where available;
- an API state machine that waits for both hostname and certificate status to become active.

The origin route still matches the customer `Host` header. Do not base Kubernetes routing on Cloudflare-specific headers unless a feature explicitly needs them.

### 10.4 Provider-neutral self-host TLS

Install cert-manager and enable its Gateway API HTTP-01 solver. The HTTP listener must permit the temporary solver route from the certificate namespace. Use ACME staging during install tests and production only after successful end-to-end validation.

Offer optional DNS-01 plugins as packaging modules, not core dependencies. A customer can also delegate `_acme-challenge.example.com` with a CNAME to a zone the installation controls, provided the selected cert-manager solver is configured to follow it.

### 10.5 Domain ownership and anti-takeover controls

A custom domain is a security-sensitive resource. The platform must:

- normalize hostnames using lower-case IDNA/Punycode rules;
- reject IP literals, public suffixes, wildcards outside allowed plans, and internal cluster names;
- enforce a unique active claim in the metadata database;
- prove domain control before routing production traffic;
- keep an auditable ownership record;
- remove the route before releasing the hostname claim;
- retain a short tombstone period so a deleted tenant cannot immediately race a new claim;
- continuously detect stale CNAMEs pointing at an unclaimed platform target;
- never let an arbitrary tenant create routes in another tenant’s namespace.

---

## 11. Multi-tenancy and namespace model

### 11.1 Default namespace boundary

Use one namespace per tenant and environment, for example:

```text
tenant-t_8f3a-prod
tenant-t_8f3a-staging
```

Place multiple applications for that tenant/environment in the namespace. This limits namespace explosion while making quotas, default-deny policy, and access boundaries straightforward.

Use one namespace per application only for customers that purchase stronger operational isolation or workloads with materially different trust profiles. A namespace is an administrative boundary, not a hard virtualization boundary; gVisor and separate clusters remain options for higher-risk code.

### 11.2 Platform namespaces

```text
kube-system           k0s and Kubernetes system components
edge-system           Traefik, Gateway, edge TLS Secrets
cert-manager           cert-manager controllers
platform-system       API, reconciler, queue, internal control services
observability         metrics, logs, dashboards, alerts
registry-system       optional in-cluster registry components
tenant-*              customer workloads only
```

Only platform automation may label a namespace as eligible to attach routes to the public Gateway.

### 11.3 Tenant baseline

Every tenant namespace receives:

- Pod Security Admission `restricted` labels;
- default-deny ingress and egress policies;
- explicit DNS egress;
- edge-to-application ingress on TCP `8080` only;
- ResourceQuota and LimitRange;
- a dedicated ServiceAccount with token automount disabled;
- application labels and ownership metadata;
- no permission to create NodePort/LoadBalancer Services, privileged Pods, host mounts, host namespaces, or public routes directly.

---

## 12. Application desired state and lifecycle

### 12.1 Product-level desired state

Keep a provider-neutral model in the product database/API:

```yaml
application:
  id: app_01J...
  tenant_id: tenant_01J...
  slug: clever-fox-21
  image:
    reference: registry.example/app@sha256:...
  container:
    port: 8080
    command: []
    env_secret_refs: []
  scale:
    min_replicas: 2
    max_replicas: 10
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: "1"
      memory: 512Mi
  health:
    readiness_path: /readyz
    liveness_path: /livez
  isolation_profile: standard       # or gvisor
  route_bindings:
    - hostname: clever-fox-21.templ-prod.supercompute.dev
      tls_mode: platform-wildcard
  status:
    phase: provisioning
```

Do not use Docker labels as the system of record. If a label-compatible developer experience is useful, translate labels into this desired state at the API boundary and then render Kubernetes resources. Kubernetes labels have size and secrecy limitations and are unsuitable for credentials or full configuration.

### 12.2 Reconciliation sequence

1. Validate image reference, resource limits, slug, and hostname.
2. Reserve application ID and hostname transactionally.
3. Ensure the tenant namespace and baseline policies exist.
4. Ensure ServiceAccount, ConfigMaps, and Secret references exist.
5. Create or patch the Deployment using server-side apply and a dedicated field manager.
6. Create the ClusterIP Service on port `8080`, targeting named port `http`.
7. Create the HTTPRoute or route-adapter resource.
8. Create or update the certificate/custom-hostname resource when required.
9. Observe Deployment availability, endpoint readiness, route conditions, certificate/provider state, and external DNS.
10. Run an HTTPS probe through the real public hostname.
11. Set `Ready` only when all required conditions pass.
12. Retry transient errors with bounded exponential backoff and a visible error code.

### 12.3 Deletion sequence

1. Mark the application `deleting` and stop accepting mutations.
2. Remove or disable public route bindings.
3. Remove external custom-hostname/provider resources.
4. Wait for edge propagation or a bounded grace period.
5. Delete workload and Service resources.
6. Delete certificate Secrets only after no route references them.
7. Retain a hostname tombstone and audit record.
8. Delete the namespace only when it contains no other applications and no retained data.

Use finalizers only where an external resource must be cleaned before Kubernetes deletion. Every finalizer path needs a documented force-removal recovery procedure.

---

## 13. Workload runtime and gVisor

Install `runsc` and `containerd-shim-runsc-v1` on every node initially so a gVisor application can be rescheduled after a node loss. Configure k0s-managed containerd with a drop-in and create a `RuntimeClass` named `gvisor`.

Use gVisor as an opt-in isolation profile, not the universal default until compatibility and performance are measured. Test:

- application startup and shutdown;
- networking, DNS, TLS, and filesystem behavior;
- required syscalls;
- language runtimes and JITs;
- observability agents;
- performance under representative concurrency;
- readiness/liveness probes;
- upgrades between pinned gVisor releases.

gVisor supplements, but does not replace, non-root execution, seccomp, dropped capabilities, NetworkPolicy, quotas, and image controls.

---

## 14. Data and storage strategy

### 14.1 Launch recommendation

Treat application containers as stateless. Prefer externally managed or separately operated services for:

- relational databases;
- object storage;
- queues;
- durable logs;
- backups.

Do not use `hostPath` or k0s local-path storage for customer production data. Local volumes make rescheduling and node replacement misleadingly appear successful while data remains tied to a failed node.

### 14.2 Optional storage product module

When persistent volumes become a product requirement, package one tested default plus a customer-supplied CSI option. Longhorn may fit a small bare-metal cluster, but it adds replicas, repair traffic, disk pressure, snapshots, backup targets, and its own failure modes. It must have a separate capacity model and restore runbook.

The platform control-plane database itself should have independent backups and preferably live outside the workload cluster for the hosted SaaS. For a small self-hosted installation, an in-cluster database is acceptable only with explicit backup and restore procedures.

---

## 15. Observability and operational components

### 15.1 Minimum launch stack

| Capability | Suggested component | Notes |
|---|---|---|
| Metrics | Prometheus-compatible collection | Cluster, node, etcd, Traefik, cert-manager, application SLI metrics. |
| Dashboards | Grafana | Private access only; dashboards are operational aids, not alerts. |
| Alerting | Alertmanager-compatible routing | Page only actionable conditions; send lower-priority notifications separately. |
| Logs | Loki plus Alloy/Fluent Bit, or customer-selected backend | Store off-node; redact secrets and auth headers. |
| Traces | OpenTelemetry, optional at launch | Add when product APIs or provisioning latency need distributed diagnosis. |
| External checks | Independent HTTPS probe | Must resolve public DNS and exercise TLS and Host routing. |
| Audit | Kubernetes audit log to off-node backend | Metadata-oriented policy; avoid secret request bodies. |

### 15.2 Required service indicators

- edge TCP/TLS success and HTTP `2xx/3xx/4xx/5xx` by route;
- provisioning duration and failure rate by reconciliation step;
- application readiness and restart rate;
- etcd member/quorum health and disk fsync latency;
- Kubernetes API readiness and request latency;
- node CPU, memory, PID, filesystem, and inode pressure;
- WireGuard latest-handshake age and packet errors;
- certificate expiry and renewal failures;
- DNS/custom-hostname activation state;
- backup age and restore-test age;
- image pull failures and registry latency.

Avoid unbounded high-cardinality labels such as raw customer URL paths, request IDs, or arbitrary hostnames in every metric. Map to stable tenant/application IDs where appropriate.

---

## 16. Infrastructure-as-code ownership

### 16.1 Ownership split

**Ansible owns:**

- OS users, packages, kernel/sysctl baseline, time sync;
- WireGuard interfaces, keys, routes, and firewall rules;
- k0s/k0sctl versions and installation;
- gVisor binaries and containerd drop-ins;
- encrypted bootstrap files such as API encryption configuration;
- cluster bootstrap and first administrator access;
- invoking Helm/kubectl for foundational add-ons;
- backup agents and node monitoring.

**Helm/Kubernetes manifests own:**

- Traefik, cert-manager, metrics/logging components;
- GatewayClass, Gateway, TLS options, issuers;
- platform services and policies;
- RuntimeClass and admission policies.

**Platform reconciler owns:**

- tenant namespaces and tenant-scoped baseline resources;
- application Deployments, Services, HTTPRoutes/IngressRoutes;
- application certificates and external domain bindings;
- application status and cleanup.

Do not let Ansible and the application reconciler manage the same Kubernetes fields.

### 16.2 Suggested repository layout

```text
infra/
  ansible.cfg
  inventories/
    local/
      hosts.yml
      group_vars/all.yml
      group_vars/vault.yml
    prod/
      hosts.yml
      group_vars/all.yml
      group_vars/vault.yml
    selfhost-reference/
      hosts.yml
      group_vars/all.yml
      group_vars/vault.yml
  roles/
    host_baseline/
    wireguard/
    firewall/
    gvisor/
    k0s/
    cluster_addons/
    backup/
  templates/
    k0sctl.yaml.j2
    encryption-config.yaml.j2
    audit-policy.yaml.j2
  kubernetes/
    gateway/
    cert-manager/
    policies/
    observability/
  helm-values/
    traefik.yaml.j2
    cert-manager.yaml.j2
  playbooks/
    bootstrap.yml
    upgrade.yml
    backup.yml
    restore-drill.yml
    validate.yml
platform/
  api/
  reconciler/
  adapters/
    kubernetes_gateway/
    traefik_crd/
    cloudflare_saas/
    cert_manager/
  schemas/
  tests/
```

### 16.3 Environment variable matrix

```yaml
# Domain and edge
platform_domain: templ-prod.supercompute.dev
platform_wildcard_hostname: "*.templ-prod.supercompute.dev"
origin_hostname: origin.templ-prod.supercompute.dev
customer_cname_target: customers.templ-prod.supercompute.dev
edge_route_provider: gateway-api       # gateway-api | traefik-crd
public_endpoint_mode: cloudflare-lb     # multi-a | cloudflare-lb | external-l4 | single-ip

# TLS
tls_platform_mode: acme-dns01-cloudflare
tls_custom_domain_mode: cloudflare-saas # cloudflare-saas | acme-http01 | acme-dns01 | byo
tls_local_mode: mkcert-static
acme_environment: production            # staging during install tests

# Cluster
k0s_version: "<pinned-supported-release>"
k0sctl_version: "<pinned-supported-release>"
wireguard_interface: wg0
wireguard_cidr: 10.44.0.0/24
calico_mtu: 1370                         # measured value, not copied blindly
pod_cidr: 10.244.0.0/16
service_cidr: 10.96.0.0/12

# Runtime
gvisor_enabled: true
gvisor_version: "<pinned-release>"

# Capacity
system_reserved_cpu: "1000m"
system_reserved_memory: "2Gi"
max_direct_gateway_certificates: 50
```

Local inventory changes these values, not the application schema:

```yaml
platform_domain: 127-0-0-1.sslip.io
public_endpoint_mode: single-ip
tls_platform_mode: mkcert-static
tls_custom_domain_mode: mkcert-static
edge_route_provider: gateway-api
```

---

## 17. Reference configuration templates

These are architecture templates, not blindly copyable production files. Render them from Ansible, pin component versions, run `helm template`, and validate all resulting APIs against the chosen k0s/Kubernetes release.

### 17.1 k0sctl topology

```yaml
apiVersion: k0sctl.k0sproject.io/v1beta1
kind: Cluster
metadata:
  name: supercompute-prod
spec:
  hosts:
    - role: controller+worker
      noTaints: true
      privateAddress: "{{ hostvars['node-1'].wireguard_ip }}"
      ssh:
        address: "{{ hostvars['node-1'].ansible_host }}"
        user: "{{ k0s_ssh_user }}"
        keyPath: "{{ k0s_ssh_key_path }}"
    - role: controller+worker
      noTaints: true
      privateAddress: "{{ hostvars['node-2'].wireguard_ip }}"
      ssh:
        address: "{{ hostvars['node-2'].ansible_host }}"
        user: "{{ k0s_ssh_user }}"
        keyPath: "{{ k0s_ssh_key_path }}"
    - role: controller+worker
      noTaints: true
      privateAddress: "{{ hostvars['node-3'].wireguard_ip }}"
      ssh:
        address: "{{ hostvars['node-3'].ansible_host }}"
        user: "{{ k0s_ssh_user }}"
        keyPath: "{{ k0s_ssh_key_path }}"
  k0s:
    version: "{{ k0s_version }}"
    config:
      apiVersion: k0s.k0sproject.io/v1beta1
      kind: ClusterConfig
      metadata:
        name: k0s
      spec:
        telemetry:
          enabled: false
        network:
          provider: calico
          podCIDR: "{{ pod_cidr }}"
          serviceCIDR: "{{ service_cidr }}"
          calico:
            mode: vxlan
            overlay: Always
            mtu: {{ calico_mtu }}
            wireguard: false
            ipAutodetectionMethod: "interface={{ wireguard_interface }}"
          nodeLocalLoadBalancing:
            enabled: true
            type: EnvoyProxy
```

Operational checks before applying:

```text
- All privateAddress values are unique WireGuard addresses.
- `k0sctl apply --dry-run` shows WireGuard API and etcd peer addresses.
- No public route is needed for 6443, 2380, 8132, 9443, or 10250.
- Every node can reach every other WireGuard IP and required port.
- The selected pod/service CIDRs do not overlap WireGuard, host, VPN, or customer LAN ranges.
```

### 17.2 gVisor containerd drop-in

`/etc/k0s/containerd.d/gvisor.toml`:

```toml
version = 3

[plugins."io.containerd.cri.v1.runtime".containerd.runtimes.runsc]
  runtime_type = "io.containerd.runsc.v1"
```

RuntimeClass:

```yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: gvisor
handler: runsc
scheduling:
  nodeSelector:
    runtime.supercompute.dev/gvisor: "true"
```

Label nodes only after the runtime smoke test succeeds:

```bash
kubectl label node node-1 runtime.supercompute.dev/gvisor=true
kubectl label node node-2 runtime.supercompute.dev/gvisor=true
kubectl label node node-3 runtime.supercompute.dev/gvisor=true
```

### 17.3 Traefik Helm values

```yaml
deployment:
  kind: DaemonSet
  minReadySeconds: 5

service:
  enabled: false

providers:
  kubernetesGateway:
    enabled: true
  # Keep enabled only when using TLSOption or the large-fleet route adapter.
  kubernetesCRD:
    enabled: true

ports:
  web:
    port: 80
    containerPort: 80
    hostPort: 80
    allowACMEByPass: true
    forwardedHeaders:
      insecure: false
      trustedIPs: []          # populated only for an actual trusted proxy
  websecure:
    port: 443
    containerPort: 443
    hostPort: 443
    forwardedHeaders:
      insecure: false
      trustedIPs: []          # Cloudflare/LB ranges in SaaS profile only

securityContext:
  runAsNonRoot: true
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: ["ALL"]
    add: ["NET_BIND_SERVICE"]

podSecurityContext:
  seccompProfile:
    type: RuntimeDefault

api:
  dashboard: false
  insecure: false

ingressRoute:
  dashboard:
    enabled: false

logs:
  general:
    level: INFO
  access:
    enabled: true

resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: "1"
    memory: 512Mi
```

The exact chart schema changes over time. Pin the chart and image digest, then test the rendered DaemonSet, security context, host ports, Gateway provider, and probes in CI.

### 17.4 Gateway

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: public-edge
  namespace: edge-system
spec:
  gatewayClassName: traefik
  listeners:
    - name: http
      protocol: HTTP
      port: 80
      allowedRoutes:
        namespaces:
          from: Selector
          selector:
            matchLabels:
              platform.supercompute.dev/public-route-access: "true"
    - name: https
      protocol: HTTPS
      port: 443
      tls:
        mode: Terminate
        certificateRefs:
          - group: ""
            kind: Secret
            name: platform-wildcard-tls
      allowedRoutes:
        namespaces:
          from: Selector
          selector:
            matchLabels:
              platform.supercompute.dev/public-route-access: "true"
```

Label only controlled namespaces:

```bash
kubectl label namespace edge-system \
  platform.supercompute.dev/public-route-access=true
kubectl label namespace tenant-t_8f3a-prod \
  platform.supercompute.dev/public-route-access=true
```

Configure Traefik’s default TLS options with TLS 1.2 or newer and strict SNI, then verify behavior using `openssl s_client`. The exact binding of implementation-specific TLS options to Gateway listeners must be validated against the pinned Traefik release.

### 17.5 Application Deployment, Service, and HTTPRoute

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: clever-fox-21
  namespace: tenant-t-8f3a-prod
  labels:
    platform.supercompute.dev/app-id: app-01jxyz
spec:
  replicas: 2
  selector:
    matchLabels:
      platform.supercompute.dev/app-id: app-01jxyz
  template:
    metadata:
      labels:
        platform.supercompute.dev/app-id: app-01jxyz
        platform.supercompute.dev/public-http: "true"
    spec:
      serviceAccountName: clever-fox-21
      automountServiceAccountToken: false
      # Set only for the gVisor isolation profile:
      # runtimeClassName: gvisor
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              platform.supercompute.dev/app-id: app-01jxyz
      containers:
        - name: app
          image: registry.example/app@sha256:REPLACE_WITH_DIGEST
          ports:
            - name: http
              containerPort: 8080
              protocol: TCP
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: "1"
              memory: 512Mi
          readinessProbe:
            httpGet:
              path: /readyz
              port: http
            initialDelaySeconds: 2
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /livez
              port: http
            initialDelaySeconds: 10
            periodSeconds: 10
          volumeMounts:
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir:
            sizeLimit: 128Mi
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: clever-fox-21
  namespace: tenant-t-8f3a-prod
automountServiceAccountToken: false
---
apiVersion: v1
kind: Service
metadata:
  name: clever-fox-21
  namespace: tenant-t-8f3a-prod
spec:
  type: ClusterIP
  selector:
    platform.supercompute.dev/app-id: app-01jxyz
  ports:
    - name: http
      port: 8080
      targetPort: http
      protocol: TCP
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: clever-fox-21
  namespace: tenant-t-8f3a-prod
spec:
  parentRefs:
    - name: public-edge
      namespace: edge-system
      sectionName: https
  hostnames:
    - clever-fox-21.templ-prod.supercompute.dev
  rules:
    - backendRefs:
        - name: clever-fox-21
          port: 8080
```

### 17.6 Cloudflare DNS-01 ClusterIssuer and wildcard Certificate

Create the token Secret from Ansible Vault; do not put the token in this manifest.

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-cloudflare-prod
spec:
  acme:
    email: platform-operations@example.com
    server: https://acme-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-cloudflare-prod-account
    solvers:
      - dns01:
          cloudflare:
            apiTokenSecretRef:
              name: cloudflare-dns-api-token
              key: api-token
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: platform-wildcard
  namespace: edge-system
spec:
  secretName: platform-wildcard-tls
  issuerRef:
    kind: ClusterIssuer
    name: letsencrypt-cloudflare-prod
  dnsNames:
    - "*.templ-prod.supercompute.dev"
    - origin.templ-prod.supercompute.dev
```

Confirm the cert-manager version’s rules for where a ClusterIssuer solver Secret must live. Centralize and tightly restrict the namespace holding DNS credentials.

### 17.7 Provider-neutral HTTP-01 ClusterIssuer

Enable Gateway API support in cert-manager before installing the issuer.

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-http01-prod
spec:
  acme:
    email: platform-operations@example.com
    server: https://acme-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-http01-prod-account
    solvers:
      - http01:
          gatewayHTTPRoute:
            parentRefs:
              - name: public-edge
                namespace: edge-system
                kind: Gateway
```

A direct custom-domain Certificate can live in `edge-system` so its TLS Secret is local to the Gateway:

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: custom-app-customer-com
  namespace: edge-system
spec:
  secretName: custom-app-customer-com-tls
  issuerRef:
    kind: ClusterIssuer
    name: letsencrypt-http01-prod
  dnsNames:
    - app.customer.com
```

The controller must not add this Secret to a Gateway listener until `Certificate/Ready=True`.

### 17.8 Local certificate

```bash
mkcert -install
mkdir -p .local-tls
mkcert \
  -cert-file .local-tls/tls.crt \
  -key-file .local-tls/tls.key \
  '127-0-0-1.sslip.io' \
  '*.127-0-0-1.sslip.io'

kubectl -n edge-system create secret tls local-wildcard-tls \
  --cert=.local-tls/tls.crt \
  --key=.local-tls/tls.key \
  --dry-run=client -o yaml | kubectl apply -f -
```

Render the Gateway `certificateRefs[0].name` as `local-wildcard-tls` and the route hostname as, for example, `clever-fox-21.127-0-0-1.sslip.io`.

Do not copy the `mkcert` root key into Git, images, shared CI artifacts, or production Ansible Vault.

---

## 18. Milestones, goals, tasks, and acceptance criteria

### Milestone 0 — Product boundaries and reliability contract

**Goal:** Agree on what the three-node launch product does and does not promise.

**Tasks:**

- Define supported OS, CPU architectures, minimum node resources, and disk layout.
- Select and pin supported k0s, Kubernetes, Traefik chart/image, Gateway API CRDs, cert-manager, Calico, and gVisor versions.
- Define launch SLOs separately for the platform API, application edge, and provisioning operations.
- Define RPO/RTO for cluster state and platform metadata.
- Decide whether customer application data is in scope for backups.
- Document the one-node-failure and two-node-failure boundaries.
- Choose platform pod/service CIDRs that do not conflict with WireGuard, customer networks, or common VPN ranges.
- Decide the maximum direct Gateway certificate count and default custom-domain adapter.

**Acceptance:** A versioned architecture decision record and support matrix exist; sales and support language matches the technical boundary.

### Milestone 1 — Reproducible three-node k0s foundation

**Goal:** Rebuild the cluster from Ansible without manual node configuration.

**Tasks:**

- Implement host baseline, WireGuard verification, firewall, time synchronization, and disk checks.
- Render k0sctl inventory with three `controller+worker` nodes and explicit WireGuard `privateAddress` values.
- Enable Calico, measured MTU, and node-local load balancing.
- Verify API/etcd/kubelet ports are unavailable from public networks.
- Reserve system resources and define critical PriorityClasses.
- Install gVisor drop-in and run a RuntimeClass smoke test.
- Capture a first control-plane backup.

**Acceptance:** A clean environment can be created twice from source; all nodes are Ready; etcd has three healthy members; cross-node Pod and Service traffic works; one node can be stopped without losing control-plane quorum.

### Milestone 2 — Edge routing and local parity

**Goal:** Route many hostnames to many Services that all use port `8080`.

**Tasks:**

- Install pinned Gateway API CRDs and Traefik DaemonSet.
- Bind `80/443` on every node with non-root `NET_BIND_SERVICE` configuration.
- Create Gateway, route namespace selector, default TLS policy, and unknown-host behavior.
- Build the application Deployment/Service/HTTPRoute template.
- Implement local `sslip.io` plus `mkcert` variables.
- Test at least 100 routes to Services using the same target port.
- Verify cross-node backend routing, readiness removal, and rolling edge upgrades.

**Acceptance:** Local and production manifests differ only by rendered variables and certificate source; no application uses NodePort or a published host port; routing remains correct after any single Pod or node restart.

### Milestone 3 — TLS and domain adapters

**Goal:** Automate all supported domain modes without making self-hosting provider-specific.

**Tasks:**

- Install cert-manager with Gateway API HTTP-01 support.
- Create staging and production issuers.
- Automate platform wildcard DNS-01 with a narrow Cloudflare token.
- Implement exact-host HTTP-01 for self-host.
- Implement BYO TLS Secret validation and rotation path.
- Implement Cloudflare for SaaS adapter, fallback origin, CNAME target, and status polling.
- Add domain normalization, unique claims, proof-of-control, tombstones, and stale-CNAME detection.
- Implement direct-certificate threshold and route-adapter switch.
- Alert on renewal failure and certificate expiry.

**Acceptance:** Platform wildcard renews in staging; a customer hostname can be onboarded and offboarded end to end; a self-hosted hostname works with a non-Cloudflare DNS provider; failed validation never creates an active public route.

### Milestone 4 — Application provisioning controller

**Goal:** Make application creation a durable, idempotent business process.

**Tasks:**

- Define database schema and provider-neutral desired-state contract.
- Implement reconciliation queue, leases, retries, and operation IDs.
- Use Kubernetes server-side apply with a dedicated field manager.
- Implement namespace baseline, Deployment, Service, route, certificate, and status reconciliation.
- Observe Kubernetes conditions rather than assuming API writes equal readiness.
- Add external synthetic HTTPS verification.
- Implement safe deletion/finalizer recovery and orphan scanning.
- Add per-step error codes suitable for customer support.

**Acceptance:** Replaying the same request is safe; process crashes do not leak routes or hostnames; reconciliation repairs manual drift; every application has a complete audit trail.

### Milestone 5 — Multi-tenancy and workload hardening

**Goal:** Prevent ordinary tenant workloads from controlling nodes, other tenants, or the public edge.

**Tasks:**

- Enforce restricted Pod Security Admission in tenant namespaces.
- Apply default-deny policies and explicit DNS/edge rules.
- Apply ResourceQuota, LimitRange, PID, and ephemeral-storage controls.
- Deny privileged, host namespace, hostPath, NodePort, LoadBalancer, and unapproved registry use.
- Disable service account token automount by default.
- Add gVisor isolation profile and compatibility test suite.
- Add image scanning and digest pinning; phase in signing enforcement.
- Run the k0s kube-bench profile and track justified exceptions.

**Acceptance:** Security tests demonstrate cross-tenant traffic denial, blocked privileged workloads, blocked node metadata/private management access, and successful operation of approved standard and gVisor applications.

### Milestone 6 — Observability, backup, restore, and upgrades

**Goal:** Operate the product without relying on intuition or undocumented heroics.

**Tasks:**

- Collect node, etcd, API, Traefik, cert-manager, application, and reconciler metrics.
- Ship cluster and audit logs off-node.
- Define alerts with owners and runbook links.
- Automate daily k0s backup and separate platform/application data backup.
- Encrypt and copy backups off-cluster.
- Perform a disposable-environment restore drill.
- Write one-controller-at-a-time and one-minor-at-a-time upgrade procedures.
- Test drain, PodDisruptionBudget, and rollback behavior.

**Acceptance:** An operator can identify a failed provisioning step, restore cluster state from a verified backup, and upgrade a canary installation using only documented procedures.

### Milestone 7 — SaaS edge and self-hosted packaging

**Goal:** Turn the architecture into two supportable commercial offerings.

**Tasks:**

- SaaS: configure Cloudflare LB health checks, Cloudflare for SaaS lifecycle, origin TLS, trusted proxy CIDRs, and abuse controls.
- Self-host: build preflight checks for DNS, ports, CIDR overlaps, resources, storage, time, and architecture.
- Produce a generated installation report with component versions and security posture.
- Provide selectable TLS and endpoint profiles without editing core templates.
- Add an offline/BYO registry option if it is a target market requirement.
- Define upgrade channels and compatibility windows.
- Redact secrets from support bundles.

**Acceptance:** A fresh self-host customer can install from documented variables without Cloudflare/AWS; SaaS customer domains survive one origin node failure; support can reproduce the exact deployed bill of materials.

### Milestone 8 — Launch validation

**Goal:** Demonstrate business readiness under expected failures and load.

**Tasks:**

- Load test route count, concurrent connections, TLS handshakes, and application provisioning.
- Kill an application Pod, Traefik Pod, node, WireGuard peer, and DNS/LB origin in controlled tests.
- Fill disk and memory in a lab to validate eviction and alerting.
- Force certificate staging renewal and provider API errors.
- Test a failed Kubernetes upgrade and restore path.
- Run external attack-surface scans against every public IP.
- Review capacity after a one-node-loss test.
- Complete incident, customer communication, and status-page exercises.

**Acceptance:** Launch checklist is signed; all P0 hardening items pass; capacity and failure results are recorded; unresolved risks have owners and explicit dates.

---

## 19. Suggested initial SLOs and business rules

These are starting points, not guarantees to publish before measurement:

- **Application edge availability:** 99.9% monthly for applications with two or more healthy replicas and the health-aware SaaS endpoint profile.
- **Platform API availability:** 99.9% monthly, excluding announced maintenance.
- **Platform-hostname provisioning:** 95% complete within 60 seconds after image availability.
- **Custom-domain provisioning:** report provider-dependent state rather than promising a fixed certificate time.
- **Certificate renewal:** alert when renewal has not succeeded by 21 days before expiry.
- **Backups:** daily cluster-state backup; platform database schedule based on promised RPO.
- **Restore drills:** at least quarterly and before major architectural migrations.
- **Version support:** one current tested release train and one previous supported train for self-host customers.

Do not grant an HA SLA to one-replica applications or deployments using health-unaware DNS without describing the reduced service level.

---

## 20. Architecture acceptance checklist

```text
[ ] Three distinct WireGuard private addresses; no CIDR overlap.
[ ] Public scan exposes only intended 80/443, WireGuard UDP, and restricted admin access.
[ ] k0s API and etcd use private addresses; three etcd members are healthy.
[ ] Calico node address is the WireGuard address; measured MTU is documented.
[ ] Traefik runs on all three nodes and no dashboard/API is public.
[ ] Platform wildcard certificate is Ready and renews in ACME staging.
[ ] Every app uses ClusterIP Service port 8080; no app NodePort/hostPort.
[ ] HTTPRoute Accepted=True and ResolvedRefs=True before app readiness.
[ ] Unknown/unclaimed SNI and Host values do not reach a tenant application.
[ ] Default-deny policies block tenant-to-tenant traffic.
[ ] PSS restricted rejects privileged and host-level tenant Pods.
[ ] gVisor smoke and compatibility tests pass on every labeled node.
[ ] One node loss preserves etcd quorum and eligible two-replica applications.
[ ] Health-aware SaaS LB removes an unhealthy origin.
[ ] Plain multi-A limitations are stated in the self-host documentation.
[ ] k0s backup and separate data backup are current and stored off-cluster.
[ ] A restore drill and an upgrade drill have passed.
[ ] Ansible Vault secrets do not appear in logs, diffs, support bundles, or Git history.
```

---

## 21. Primary references

All implementation work should pin version-specific documentation rather than copying examples from moving `head` pages.

- k0s production installation with k0sctl: <https://docs.k0sproject.io/head/k0sctl-install/>
- k0s control-plane HA: <https://docs.k0sproject.io/head/high-availability/>
- k0s configuration reference: <https://docs.k0sproject.io/head/configuration/>
- k0s node-local load balancing: <https://docs.k0sproject.io/head/nllb/>
- k0s runtime and gVisor integration: <https://docs.k0sproject.io/head/runtime/>
- Kubernetes Gateway API project: <https://gateway-api.sigs.k8s.io/>
- Gateway API specification, including listener certificate references: <https://gateway-api.sigs.k8s.io/reference/api-spec/main/spec/>
- Kubernetes Ingress guidance: <https://kubernetes.io/docs/concepts/services-networking/ingress/>
- Traefik Helm chart examples: <https://github.com/traefik/traefik-helm-chart/blob/master/EXAMPLES.md>
- Traefik Helm chart values: <https://github.com/traefik/traefik-helm-chart/blob/master/traefik/values.yaml>
- Traefik Gateway API provider: <https://doc.traefik.io/traefik/reference/routing-configuration/kubernetes/gateway-api/>
- Traefik TLS options: <https://doc.traefik.io/traefik/reference/routing-configuration/http/tls/tls-options/>
- cert-manager HTTP-01 with Gateway API: <https://cert-manager.io/docs/configuration/acme/http01/>
- cert-manager DNS-01: <https://cert-manager.io/docs/configuration/acme/dns01/>
- cert-manager Cloudflare DNS-01: <https://cert-manager.io/docs/configuration/acme/dns01/cloudflare/>
- Cloudflare for SaaS setup: <https://developers.cloudflare.com/cloudflare-for-platforms/cloudflare-for-saas/start/getting-started/>
- Cloudflare Full (strict): <https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/>
- sslip.io documentation: <https://sslip.io/>
- mkcert project documentation: <https://github.com/FiloSottile/mkcert>

---

## 22. Final recommendation

Launch with the smallest architecture that has a clear failure model:

```text
3 x k0s controller+worker
+ embedded etcd
+ Calico VXLAN over WireGuard
+ Traefik DaemonSet on host ports 80/443
+ Gateway API HTTPRoutes
+ cert-manager
+ Cloudflare wildcard DNS-01
+ Cloudflare for SaaS for hosted custom domains
+ HTTP-01/BYO/DNS-01 options for self-hosted custom domains
+ opt-in gVisor RuntimeClass
+ one idempotent application reconciler
+ off-node monitoring, logs, and backups
```

This directly solves the port-`8080` routing problem, maintains local/production parity, remains provider-neutral for self-hosting, and avoids loading the first release with distributed-storage and operator-framework complexity that has not yet earned its operational cost.
