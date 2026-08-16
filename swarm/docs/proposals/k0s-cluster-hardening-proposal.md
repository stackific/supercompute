# Supercompute k0s Cluster Hardening Runbook
## Pragmatic, Business-Ready Security for a Three-Node SaaS and Self-Hosted Platform

**Status:** Recommended operational baseline  
**Audience:** Platform engineering, SRE/operations, security reviewers, and self-hosting administrators  
**Last reviewed:** 2026-08-16  
**Applies to:** Three combined k0s controller/worker nodes, Traefik edge, Calico, WireGuard, cert-manager, optional gVisor, and Ansible Vault

---

## 1. Purpose and hardening philosophy

This runbook aims for a defensible commercial platform without turning a three-node product into an unmaintainable imitation of a heavily regulated bank environment.

The priorities are:

1. Keep control-plane and node-management services off the public internet.
2. Prevent an ordinary tenant workload from controlling the host, the cluster, another tenant, or the public edge.
3. Make secrets, certificates, and administrator credentials difficult to steal accidentally.
4. Preserve enough logs, backups, and operating evidence to investigate and recover from failure.
5. Make upgrades and security fixes routine rather than heroic.
6. Prefer controls that can be tested continuously over long policy documents that are never exercised.

No single control is treated as magic. WireGuard does not replace a firewall. gVisor does not replace Pod Security Standards. encryption at rest does not protect a compromised controller host. Cloudflare does not secure the origin if the origin accepts arbitrary direct traffic. A backup that has never been restored is not a recovery capability.

---

## 2. Priority plan

### P0 — Complete before public production traffic

```text
[ ] Public attack surface restricted to intended 80/443, WireGuard, and admin path.
[ ] Kubernetes API, etcd, kubelet, k0s join API, and metrics unavailable publicly.
[ ] Pinned and verified k0s, k0sctl, Traefik, cert-manager, and gVisor artifacts.
[ ] Three healthy etcd members and tested one-node failure.
[ ] Unique administrator access; no shared production SSH key or kubeconfig.
[ ] Kubernetes Secrets encrypted at rest; encryption key backed up separately.
[ ] Tenant namespaces enforce Pod Security `restricted`.
[ ] Default-deny NetworkPolicy plus explicit DNS and edge-to-app rules.
[ ] Tenant Pods run non-root, drop all capabilities, use RuntimeDefault seccomp,
    disable privilege escalation, and have resource requests/limits.
[ ] Traefik dashboard/API not public; forwarded headers trusted only from known proxies.
[ ] TLS renewal alerts and unknown-host behavior tested.
[ ] Daily k0s control-plane backup plus separate application/platform data backup.
[ ] Off-node monitoring and logs, including actionable etcd, node, edge, and cert alerts.
[ ] Documented incident isolation and node rebuild procedure.
```

### P1 — Complete during the first operating month

```text
[ ] OIDC and MFA for human Kubernetes access; break-glass account tested.
[ ] Native admission policies for service types, host access, resources, and images.
[ ] Image scanning, SBOM generation, digest pinning, and registry allow-listing.
[ ] Quarterly restore drill completed in a disposable environment.
[ ] k0s/Traefik/cert-manager upgrade drill completed on a canary installation.
[ ] External attack-surface scan and internal cross-tenant tests automated.
[ ] Cloudflare for SaaS origin health checking and direct-origin restrictions tested.
[ ] Ansible Vault key rotation and secret-redaction review completed.
```

### P2 — Add when risk, scale, or customer requirements justify it

```text
[ ] Separate controller and worker nodes when combined-node contention becomes material.
[ ] External KMS v2 for Kubernetes encryption keys.
[ ] Enforced image-signature admission after the signing pipeline is reliable.
[ ] Dedicated egress proxy/gateway for tenant internet access and domain-level controls.
[ ] Per-tenant clusters or stronger sandbox tiers for hostile/untrusted code.
[ ] Multi-cluster regional failover and independent failure domains.
[ ] Formal external penetration test and compliance mapping for target markets.
```

---

## 3. Threat model and trust boundaries

### 3.1 Assets to protect

- Kubernetes and k0s signing keys, CAs, join tokens, and administrator kubeconfigs.
- etcd contents, including Kubernetes Secrets and tenant desired state.
- Ansible Vault identities/passwords and decrypted temporary files.
- Cloudflare, DNS, registry, and ACME credentials.
- Customer TLS private keys in `edge-system`.
- Platform metadata database and domain-ownership records.
- Tenant application data and credentials.
- Public routing integrity: one customer must never receive another customer’s traffic.
- Availability of edge, etcd quorum, WireGuard, DNS, certificate renewal, and backups.

### 3.2 Relevant attackers and failure sources

- Internet scanning and opportunistic exploitation of public services.
- A malicious or compromised tenant container.
- A compromised application image or dependency.
- Stolen administrator workstation credentials.
- Misconfigured Ansible, Kubernetes RBAC, route, DNS, or firewall rules.
- A compromised node or hosting-provider account.
- Certificate/domain takeover through stale CNAMEs or released hostname claims.
- Accidental deletion, failed upgrade, disk exhaustion, or two-node failure.
- Supply-chain compromise of downloaded binaries or container images.

### 3.3 Trust-boundary diagram

```text
UNTRUSTED INTERNET
      |
      | only TCP 80/443 to edge; WireGuard UDP to authenticated peers
      v
+-------------------------- PUBLIC NODE INTERFACE --------------------------+
| Host firewall                                                            |
|  - allow edge ports                                                       |
|  - drop API/etcd/kubelet/join/NodePort                                    |
|  - restrict SSH                                                           |
+-------------------------------+--------------------------------------------+
                                |
                                v
+-------------------------------+--------------------------------------------+
| Traefik edge namespace                                                    |
| Narrow hostPort/capability exception; no dashboard; strict TLS/SNI;       |
| controlled Gateway attachment; trusted proxy headers only                 |
+-------------------------------+--------------------------------------------+
                                |
                                v
+-------------------------------+--------------------------------------------+
| TENANT NAMESPACE — UNTRUSTED WORKLOAD BOUNDARY                            |
| PSS restricted + admission policy + default-deny NetworkPolicy + quotas   |
| non-root runc or gVisor; no host access; no node ports; no route control   |
+-------------------------------+--------------------------------------------+
                                |
                  explicitly allowed dependencies only
                                v
+-------------------------------+--------------------------------------------+
| PLATFORM / DATA SERVICES                                                  |
| separate service accounts, RBAC, Secrets, backups, logging, monitoring    |
+----------------------------------------------------------------------------+

WIREGUARD TRUSTED NODE NETWORK
  node-to-node API, etcd peer, kubelet, Konnectivity and Calico traffic.
  Compromise of a WireGuard peer still requires host firewall and service auth.
```

### 3.4 Honest security boundary

A combined controller/worker node is a high-value system. Root compromise of one controller exposes local control-plane keys and can enable serious cluster attacks. Encryption at rest primarily protects against direct etcd-data exposure, not against root on an API-server host. The practical response to suspected node root compromise is isolation, credential rotation, and rebuild—not “cleaning” the node in place.

---

## 4. Step 0 — Establish ownership, inventory, and change control

### Objective

Make every security control and operational dependency attributable to an owner and a version.

### Actions

1. Maintain a machine-readable bill of materials:
   - OS and kernel;
   - k0s and Kubernetes version;
   - k0sctl version;
   - Traefik chart, image tag, and image digest;
   - Gateway API CRD version;
   - cert-manager version and image digests;
   - Calico version inherited from k0s;
   - gVisor release and checksums;
   - observability and backup components.
2. Assign owners for:
   - node/OS security;
   - Kubernetes platform;
   - edge and DNS;
   - certificates;
   - registry/supply chain;
   - backups and restore;
   - incident response.
3. Record data classification and retention for platform metadata, logs, audit logs, and customer data.
4. Define change windows and an emergency patch path.
5. Keep an exception register. Every exception includes risk, owner, reason, compensating control, and review date.

### Verify

```text
- An operator can identify the exact version and digest running for every critical component.
- Every alert and runbook has an owner.
- Unsupported or end-of-life components are visible rather than discovered during an incident.
```

---

## 5. Step 1 — Harden the operating-system baseline

### Objective

Reduce unnecessary host attack surface without applying generic “CIS” settings that break Kubernetes, overlays, or multi-homed WireGuard routing.

### Actions

#### 5.1 Use a small supported OS set

Support one or two tested Linux distributions and specific release families. Do not claim support for every distribution. Use minimal images, but retain the debugging tools required by the support runbook.

#### 5.2 Administration and SSH

- Create a named administration user with audited `sudo` access.
- Use SSH keys only; disable password authentication.
- Prefer SSH over WireGuard. When public SSH is retained, restrict it to fixed administration CIDRs and rate-limit it.
- Disable direct root password login. `PermitRootLogin prohibit-password` may be acceptable for automated bootstrap, but a named sudo user is better for accountability.
- Do not share one private SSH key across production, staging, and customers.
- Store host keys and expected fingerprints; investigate unexpected changes.
- Disable agent forwarding unless a specific workflow requires it.

#### 5.3 Updates

- Apply security updates on a staged cadence.
- Do not permit unattended automatic reboots on all three nodes.
- Patch and reboot one node at a time after health and capacity checks.
- Keep an emergency process for remotely exploitable kernel/container-runtime vulnerabilities.

#### 5.4 Host services

- Remove or disable unused daemons, compilers, discovery agents, and public management panels.
- Do not install Docker Engine on cluster nodes merely because images are called “Docker images.” k0s already manages containerd.
- Disable public listening sockets that are not in the firewall matrix.
- Run a recurring `ss -lntup` inventory and diff it against the approved list.

#### 5.5 Time, filesystems, and capacity

- Configure reliable NTP/chrony. TLS, etcd, audit, and certificate issuance depend on correct time.
- Separate or closely monitor space used by `/var/lib/k0s`, kubelet/container data, logs, and backups.
- Alert on filesystem and inode pressure before Kubernetes reaches eviction thresholds.
- Encrypt node disks when the hosting model and threat profile justify protection against offline disk access.
- Do not place container runtime directories on `noexec` filesystems.
- Keep local backups off the same filesystem that can fill because of container images or logs.

#### 5.6 Kernel and Kubernetes prerequisites

- Use cgroup v2 where supported by the chosen OS/k0s combination.
- Disable swap for the initial supported configuration unless swap behavior has been intentionally tested and documented.
- Load only required modules, including overlay/network modules needed by the tested CNI.
- Enable IP forwarding as required by Kubernetes.
- Enable AppArmor or SELinux enforcement where supported and tested.
- Use kubelet `--protect-kernel-defaults=true` only after Ansible sets all required sysctls; otherwise the node may fail to start.
- Do not blindly set strict reverse-path filtering on multi-homed/overlay nodes. Test `rp_filter` with WireGuard and Calico; loose mode is often safer than strict mode.
- Disable source routing and ICMP redirects, but preserve ICMP needed for diagnostics and path-MTU discovery.

### Ansible implementation rules

- Host-baseline roles must be idempotent.
- Reboots are explicit, serial, and health-gated.
- Use handlers rather than restarting networking/k0s on every run.
- Never `flush ruleset` or reset all iptables/nftables tables after Kubernetes is active.

### Verify

```bash
sudo k0s sysinfo
sudo ss -lntup
systemctl --failed
findmnt
chronyc tracking || timedatectl status
```

Run a vulnerability scanner appropriate to the supported OS, but triage findings based on actual package exposure and reachable attack surface rather than raw count.

---

## 6. Step 2 — Enforce the network and firewall boundary

### Objective

Expose only the application edge publicly and keep cluster-management traffic on WireGuard.

### 6.1 Public-interface rule matrix

| Port/protocol | Source | Action | Purpose |
|---|---|---|---|
| TCP 80 | Any | Allow | HTTP redirect and ACME HTTP-01 challenge. |
| TCP 443 | Any | Allow | Public HTTPS edge. |
| UDP WireGuard port, commonly 51820 | Peer public IPs where stable; otherwise required sources | Allow | Existing node/admin WireGuard tunnel. |
| TCP 22 | WireGuard/admin CIDRs only | Allow or omit | Restricted administration. |
| ICMP/ICMPv6 | Appropriate types | Allow/rate-limit | PMTU, diagnostics, IPv6 correctness. Do not blanket-drop. |
| TCP 6443 | Public | Drop | Kubernetes API must not be public. |
| TCP 2380 | Public | Drop | etcd peer. |
| TCP 8132/9443 | Public | Drop | Konnectivity and k0s join API. |
| TCP 10250 | Public | Drop | kubelet API. |
| UDP 4789 | Public | Drop | Calico VXLAN is WireGuard-only. |
| TCP/UDP 30000-32767 | Public | Drop | No public NodePort range. |
| Everything else inbound | Public | Drop | Default deny. |

### 6.2 WireGuard-interface rule matrix

| Port/protocol | Source | Destination | Purpose |
|---|---|---|---|
| TCP 6443 | nodes and approved admin network | all controllers | Kubernetes API. |
| TCP 2380 | controller WireGuard IPs | controller WireGuard IPs | etcd peer replication. |
| TCP 8132 | cluster nodes | controllers | Konnectivity agent. |
| TCP 9443 | controlled joining nodes/controllers | controllers | k0s join API. Close after install only if lifecycle tests show it is safe. |
| TCP 10250 | control plane/authorized monitoring | all nodes | kubelet API. |
| UDP 4789 | node WireGuard IPs | node WireGuard IPs | Calico VXLAN. |
| TCP 22 | admin WireGuard addresses | nodes | SSH. |
| Other control metrics | explicitly required sources | explicitly bound destinations | Monitoring only; avoid `0.0.0.0` public exposure. |

Do not expose etcd client port `2379` to the network when k0s keeps it local. Keep Konnectivity administration port `8133` local/private. Block kube-proxy health/metrics ports from public networks even when processes bind broadly.

### 6.3 WireGuard rules

- Give each node a unique `/32` or tightly scoped address.
- Restrict peer `AllowedIPs` to intended node/admin networks; avoid `0.0.0.0/0` unless the tunnel is intentionally the default route.
- Monitor latest handshake age and transfer counters.
- Use persistent keepalive only when NAT requires it.
- Rotate peer keys with a documented overlapping transition rather than replacing all peers simultaneously.
- Prevent overlap between WireGuard, pod, Service, host, VPN, and customer LAN CIDRs.

### 6.4 Firewall implementation caution

Kubernetes, kube-proxy, containerd/CNI, and the host firewall all manipulate packet processing. Use one host-firewall system and a dedicated Ansible-owned table/chain. Do not run an Ansible task that flushes Kubernetes-managed rules after k0s starts. Validate rule order after every OS or kube-proxy mode change.

A safe pattern is:

```text
- Ansible owns a clearly named host-input table/chain.
- Kubernetes/CNI own their own tables/chains.
- Ansible changes only its table and never replaces the whole ruleset.
- Validation tests confirm Pod-to-Service, cross-node, DNS, and public edge traffic.
```

### 6.5 Outbound policy

Hosts need documented outbound access for:

- DNS and NTP;
- OS repositories;
- pinned OCI registries;
- ACME and DNS-provider APIs;
- monitoring/log shipping;
- backup destination;
- identity provider, if used.

Use an egress proxy or host allow-list later if customer requirements justify the maintenance cost. Do not accidentally block certificate renewal or security updates.

### Verify

From an external system:

```bash
nmap -Pn -sS -p- <node-public-ip>
nmap -Pn -sU -p <wireguard-port> <node-public-ip>
```

From each node over WireGuard, test required ports to every peer. From a test Pod, verify DNS, Service routing, and approved egress. Store results from CI/lab validation rather than relying on a one-time manual check.

---

## 7. Step 3 — Install k0s from pinned, verified artifacts

### Objective

Make cluster installation reproducible and resistant to accidental “latest” upgrades or tampered downloads.

### Actions

1. Pin k0s and k0sctl versions in inventory.
2. Verify release checksums/signatures using the project’s documented verification process.
3. Prefer a controlled internal artifact mirror for production and self-hosted release bundles.
4. Run `k0s sysinfo` before installation.
5. Use k0sctl with three `controller+worker` hosts, unique WireGuard `privateAddress` values, and `noTaints: true`.
6. Do not use the `--single` flag.
7. Enable node-local load balancing for worker-to-control-plane resilience.
8. Inspect `k0sctl apply --dry-run` on multi-homed nodes; verify API and etcd peer addresses are WireGuard addresses.
9. Keep the Kubernetes API behind WireGuard/firewall even if it binds more broadly than intended.
10. Disable k0s telemetry when product policy requires it.

### Verify

```bash
kubectl get nodes -o wide
kubectl -n kube-system get pods -o wide
kubectl get --raw='/readyz?verbose'
sudo k0s status
```

Verify three etcd members and test stopping one node. Never “force” a two-member partition to continue; restore quorum or rebuild the missing member safely.

---

## 8. Step 4 — Secure administrator identity, API access, and RBAC

### Objective

Ensure every human and automation identity has only the access it needs and can be revoked independently.

### Actions

#### 8.1 Human access

- Use the initial admin kubeconfig only for bootstrap and break-glass recovery.
- Integrate an OIDC identity provider with MFA for normal human access.
- Map IdP groups to Kubernetes roles; avoid individual ad hoc ClusterRoleBindings.
- Use separate groups such as:
  - `platform-readonly`;
  - `platform-operators`;
  - `security-auditors`;
  - `cluster-admin-breakglass`.
- Do not share one admin certificate or kubeconfig among employees.
- Set administrator kubeconfig files to mode `0600`; keep them out of shell history, ticket attachments, and support bundles.
- Store break-glass credentials encrypted offline, test them quarterly, and alert when used.

#### 8.2 API reachability

- Allow TCP `6443` only through WireGuard or a private management endpoint.
- Do not publish a Kubernetes dashboard.
- Disable anonymous API authentication after validating k0s and health-check compatibility with the pinned release.
- Review API server SANs so certificates contain only required addresses/names.

#### 8.3 Automation identities

- Give the platform reconciler a dedicated ServiceAccount and narrowly scoped ClusterRole/RoleBindings.
- Separate permissions for namespace bootstrap, workload reconciliation, edge TLS, and external-provider credentials where practical.
- Use projected, short-lived ServiceAccount tokens; disable token automount for workloads that do not call the API.
- Do not give CI a permanent cluster-admin kubeconfig.
- Restrict `create` on Pods/Deployments because it can be equivalent to code execution in the permitted namespace.
- Restrict `create` on RoleBinding/ClusterRoleBinding and `impersonate` especially carefully.

#### 8.4 Periodic review

```bash
kubectl auth can-i --list --as=<identity>
kubectl get clusterrolebindings,rolebindings -A
kubectl get serviceaccounts -A
```

Review bindings monthly and whenever staff roles change.

---

## 9. Step 5 — Use Ansible Vault safely

### Objective

Protect infrastructure bootstrap secrets without introducing an additional SOPS/age stack the operating team does not want.

### Actions

1. Use separate Vault IDs for environments and customer packages:

```text
dev
staging
prod
customer-<installation-id>
```

2. Keep Vault password files/scripts outside the repository and outside ordinary workstation backups.
3. Prefer an executable password client backed by the organization’s password manager or CI secret store.
4. Keep a separately controlled recovery copy. Losing the Vault identity can make installation recovery impossible.
5. Store only secret values in vaulted files; keep variable names and structure visible when possible so code review remains useful.
6. Mark every secret-handling Ansible task with:

```yaml
no_log: true
diff: false
```

7. Remember that `no_log` on one task does not protect a registered value printed by a later `debug` task.
8. Do not use high Ansible verbosity in production secret workflows unless output is captured and reviewed securely.
9. Render secret files with mode `0600`, owner `root`, atomic replacement, and explicit deletion of temporary plaintext.
10. Never place decrypted Vault content in `/tmp` without restrictive permissions.
11. Rekey after staff departures, suspected exposure, or scheduled key-rotation events.
12. Scan Git history and CI logs for leaked tokens even when current files are encrypted.

### Suggested layout

```yaml
# group_vars/all.yml — non-secret
cloudflare_api_token_secret_name: cloudflare-dns-api-token
kubernetes_encryption_key_name: key-2026-01

# group_vars/vault.yml — encrypted with environment Vault ID
vault_cloudflare_dns_api_token: "..."
vault_kubernetes_secretbox_key_b64: "..."
vault_registry_pull_password: "..."
```

### Verify

- CI can decrypt only the target environment.
- A developer with dev access cannot decrypt prod/customer files.
- `ansible-playbook --check --diff` does not print secret material.
- Rendered files and Kubernetes Secret manifests do not remain in CI workspaces after the job.

---

## 10. Step 6 — Encrypt Kubernetes Secrets at rest

### Objective

Ensure a copied etcd database does not reveal Secret values in plaintext.

### Design choice

Use the Kubernetes `secretbox` provider for the pragmatic local-key baseline. It uses a 32-byte key and avoids the rotation constraints of AES-GCM. This protects against direct etcd exposure but not against root compromise of a controller containing the encryption key. External KMS v2 can be added later for higher assurance.

### 10.1 Generate and store the key

Generate a 32-byte random key and base64-encode it on a trusted administration system:

```bash
head -c 32 /dev/urandom | base64
```

Store it in Ansible Vault, not in Git. Keep an encrypted recovery copy outside the cluster. If this key is lost, an etcd backup containing encrypted Secrets may be unrecoverable.

### 10.2 EncryptionConfiguration template

`/etc/k0s/encryption-config.yaml` on every controller, mode `0600`:

```yaml
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources:
      - secrets
    providers:
      - secretbox:
          keys:
            - name: key-2026-01
              secret: "{{ vault_kubernetes_secretbox_key_b64 }}"
      - identity: {}
```

`identity` must be last so existing plaintext values can still be read during migration while all new writes use `secretbox`.

Configure the API server through the k0s configuration:

```yaml
spec:
  api:
    extraArgs:
      encryption-provider-config: /etc/k0s/encryption-config.yaml
```

Validate the exact flag and path against the pinned Kubernetes/k0s release.

### 10.3 Safe rollout

1. Take a current k0s backup and verify it is copied off-cluster.
2. Render the same encryption configuration to all controllers.
3. Restart/upgrade one controller at a time, preserving etcd quorum.
4. Verify API reads and writes after every controller.
5. Rewrite existing Secrets through the API so they are stored using the first provider. A commonly used command is:

```bash
kubectl get secrets --all-namespaces -o json | kubectl replace -f -
```

Run this first in staging, inspect errors, and avoid doing it during peak load.
6. Verify new and rewritten Secret data is not visible as plaintext in an etcd snapshot inspection procedure.
7. Record the active key name and rotation date.

### 10.4 Key rotation

1. Generate `key-2026-02`.
2. Put the new key first, old key second, `identity` last.
3. Restart controllers one at a time.
4. Rewrite Secrets.
5. Verify backups and restores can decrypt current data.
6. Remove the old key only after all Secrets are rewritten and a restore test passes.

Never remove a decryption key merely because the configuration deployed successfully.

---

## 11. Step 7 — Enable useful Kubernetes audit logging

### Objective

Record who changed security-sensitive cluster resources without logging Secret bodies or creating an unbounded local disk problem.

### 11.1 Audit policy

`/etc/k0s/audit-policy.yaml`:

```yaml
apiVersion: audit.k8s.io/v1
kind: Policy
omitStages:
  - RequestReceived
rules:
  # Avoid noisy health probes.
  - level: None
    nonResourceURLs:
      - /healthz*
      - /livez*
      - /readyz*
      - /version

  # Never record Secret or token request bodies.
  - level: Metadata
    resources:
      - group: ""
        resources:
          - secrets
          - serviceaccounts/token
      - group: authentication.k8s.io
        resources:
          - tokenreviews
      - group: authorization.k8s.io
        resources:
          - subjectaccessreviews
          - selfsubjectaccessreviews

  # Record request objects for high-impact policy/routing/RBAC writes.
  - level: Request
    verbs: ["create", "update", "patch", "delete", "deletecollection"]
    resources:
      - group: rbac.authorization.k8s.io
      - group: gateway.networking.k8s.io
      - group: networking.k8s.io
        resources: ["networkpolicies", "ingresses"]
      - group: admissionregistration.k8s.io
      - group: cert-manager.io
        resources: ["issuers", "clusterissuers", "certificates"]

  # Metadata is a practical default for everything else.
  - level: Metadata
```

Request-level logging can still capture sensitive values placed incorrectly in ordinary object specs. Keep credentials in Secret objects and review what is logged.

### 11.2 API server flags

```yaml
spec:
  api:
    extraArgs:
      audit-policy-file: /etc/k0s/audit-policy.yaml
      audit-log-path: /var/log/k0s/audit.log
      audit-log-maxage: "30"
      audit-log-maxbackup: "10"
      audit-log-maxsize: "100"
```

Validate all flags against the pinned release. Ship audit logs off-node and protect the destination from tenant access. Local rotation is not a substitute for central retention.

### 11.3 Alerts

Alert on:

- new cluster-admin bindings;
- changes to Gateway/GatewayClass/listeners;
- changes to encryption or audit configuration;
- privileged namespace or admission exemptions;
- Secret reads by unusual identities;
- deletion of NetworkPolicy, ResourceQuota, or Pod Security labels;
- use of break-glass identities.

---

## 12. Step 8 — Enforce Pod Security Standards

### Objective

Block common host-escape and privilege configurations before a tenant Pod is created.

### 12.1 Tenant namespace labels

Pin the policy version to the Kubernetes minor you deploy rather than using `latest` invisibly:

```yaml
metadata:
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: v1.36  # example: match deployed minor
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/audit-version: v1.36
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/warn-version: v1.36
```

Update the pinned version deliberately during upgrades after testing workload compatibility.

### 12.2 Required application security context

```yaml
spec:
  automountServiceAccountToken: false
  securityContext:
    runAsNonRoot: true
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: app
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
```

Use a writable `emptyDir` for `/tmp` and other ephemeral paths. Build images that run with a fixed non-zero UID and do not require root-owned runtime mutations.

### 12.3 Edge-system exception

Traefik uses `hostPort: 80/443`, which does not fit the restricted tenant profile. Treat `edge-system` as a narrowly controlled platform exception:

- only platform administrators and the add-on deployment process can write there;
- tenant controllers cannot create arbitrary Pods or Secrets there;
- Traefik runs non-root and adds only `NET_BIND_SERVICE`;
- `hostNetwork`, privileged mode, host PID/IPC, and hostPath remain disallowed by separate admission policy;
- the exception is documented and reviewed after chart upgrades.

Do not weaken tenant namespaces merely because the edge component needs a host-level port.

### Verify

Attempt to create Pods with `privileged: true`, hostPath, host networking, root UID, unconfined seccomp, or added capabilities in a tenant namespace. Every test must be rejected and logged.

---

## 13. Step 9 — Add native admission guardrails

### Objective

Enforce platform-specific rules that Pod Security Admission does not cover.

### Recommended launch controls

Use Kubernetes ValidatingAdmissionPolicy for a small set of stable rules, or a carefully maintained policy engine if the team needs richer reporting. Avoid installing multiple competing admission engines.

Deny tenant resources that:

- use `hostNetwork`, `hostPID`, or `hostIPC`;
- use hostPath, privileged containers, or unsafe capabilities;
- create Service types `NodePort` or `LoadBalancer`;
- set `externalIPs` on Services;
- use `:latest` or an unapproved registry;
- omit CPU/memory requests and memory limits;
- omit readiness/liveness probes for public applications;
- set `automountServiceAccountToken: true` without an approved exception;
- create Gateway, GatewayClass, ClusterIssuer, ClusterRoleBinding, or public route resources directly;
- reference a RuntimeClass outside the approved set;
- use host ports outside the edge exception;
- exceed configured ephemeral storage or replica limits.

Start policies in `Audit`/warn mode in staging, fix legitimate workloads, then enforce. Every denial should produce a customer-safe error message and an internal policy identifier.

### Supply-chain enforcement phases

1. Reject `:latest`; require explicit tags or digests.
2. Require approved registries.
3. Prefer image digests in reconciler-rendered Deployments.
4. Scan and generate SBOMs in CI.
5. Sign release images.
6. Enforce signatures only after signing, rotation, and emergency override paths are proven.

A broken admission webhook can stop cluster writes. Native ValidatingAdmissionPolicy avoids that external availability dependency for simple CEL rules.

---

## 14. Step 10 — Enforce tenant NetworkPolicy

### Objective

Make tenant network access explicit instead of accepting Kubernetes’ default allow-all behavior.

### 14.1 Default deny

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: tenant-t-8f3a-prod
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
```

### 14.2 Allow cluster DNS

Verify the CoreDNS labels in the pinned k0s release before applying:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: tenant-t-8f3a-prod
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
```

A default-deny egress policy blocks DNS unless this or an equivalent rule exists.

### 14.3 Allow edge to public application port

Label the Traefik namespace and Pods under platform control, then allow only that source to Pods explicitly marked public:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-public-edge
  namespace: tenant-t-8f3a-prod
spec:
  podSelector:
    matchLabels:
      platform.supercompute.dev/public-http: "true"
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: edge-system
          podSelector:
            matchLabels:
              app.kubernetes.io/name: traefik
      ports:
        - protocol: TCP
          port: 8080
```

Because Traefik uses `hostPort` rather than `hostNetwork`, its proxy connections should originate from the Traefik Pod networking identity. Confirm this behavior in the pinned Calico/Traefik setup.

### 14.4 Application egress profiles

Offer explicit profiles rather than one permanent allow-all rule:

- `none`: DNS only;
- `web`: DNS plus TCP `80/443` to public destinations, excluding private/link-local ranges where supported and tested;
- `database`: named private destination CIDRs and ports;
- `custom`: reviewed destination list;
- `unrestricted`: separately priced/risk-accepted profile with monitoring.

Standard NetworkPolicy does not filter by DNS name. For domain-based controls, introduce an egress proxy/gateway or a CNI-specific policy only when operationally justified.

Block access to:

- node WireGuard and management subnets;
- Kubernetes API unless the ServiceAccount explicitly needs it;
- cloud metadata endpoints such as link-local `169.254.169.254`;
- other tenant namespace CIDRs/services;
- platform databases and monitoring backends except approved interfaces.

### 14.5 NetworkPolicy limitations

- Policy is Layer 4, not an HTTP authorization system.
- NAT/source rewriting can change how `ipBlock` rules behave; test Calico’s actual path.
- Policy application is not necessarily instantaneous at Pod creation.
- Host-network Pods have implementation-dependent policy behavior; this is another reason to avoid `hostNetwork` for Traefik.

### Verify

Automate probes that prove:

```text
tenant A -> tenant B                 denied
tenant -> node WireGuard IP          denied
tenant -> kube-apiserver             denied unless explicitly authorized
Traefik -> public app :8080          allowed
random tenant Pod -> public app      denied unless policy allows it
app -> DNS                            allowed
app -> unapproved private network    denied
```

---

## 15. Step 11 — Protect capacity and control-plane reliability

### Objective

Prevent a tenant from exhausting CPU, memory, PIDs, storage, or API objects on combined controller/worker nodes.

### 15.1 LimitRange

```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: tenant-defaults
  namespace: tenant-t-8f3a-prod
spec:
  limits:
    - type: Container
      defaultRequest:
        cpu: 100m
        memory: 128Mi
        ephemeral-storage: 128Mi
      default:
        cpu: "1"
        memory: 512Mi
        ephemeral-storage: 1Gi
      max:
        cpu: "4"
        memory: 8Gi
        ephemeral-storage: 10Gi
```

Defaults are a safety net. The platform API should still require explicit product-tier resources.

### 15.2 ResourceQuota

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: tenant-quota
  namespace: tenant-t-8f3a-prod
spec:
  hard:
    requests.cpu: "4"
    requests.memory: 8Gi
    limits.cpu: "12"
    limits.memory: 16Gi
    requests.ephemeral-storage: 8Gi
    limits.ephemeral-storage: 20Gi
    pods: "40"
    services: "40"
    services.nodeports: "0"
    persistentvolumeclaims: "0"   # raise only for storage-enabled plans
    secrets: "100"
    configmaps: "100"
```

### 15.3 Node reservations and priority

- Configure kube/system reservations based on measurement.
- Give etcd/control-plane processes adequate dedicated host resources.
- Create high PriorityClasses for Traefik, CoreDNS, cert-manager, CNI, and platform reconciliation.
- Do not grant tenants permission to use critical platform PriorityClasses.
- Configure eviction thresholds and alert before they trigger.
- Set Pod PID limits where supported.
- Limit image/cache and log growth; garbage collection must be monitored.

### 15.4 Availability controls

- Two or more replicas for HA application tiers.
- TopologySpreadConstraints across `kubernetes.io/hostname`.
- PodDisruptionBudget that permits one node drain but does not make upgrades impossible.
- Readiness probes that represent ability to serve traffic, not merely process existence.
- Startup probes for slow applications rather than large liveness delays.
- HorizontalPodAutoscaler only after metrics and maximum replica quotas are defined.

### Verify

Test namespace quota exhaustion, memory OOM, ephemeral-storage pressure, and a one-node drain. Confirm platform-critical Pods remain scheduled and alerts arrive before total node exhaustion.

---

## 16. Step 12 — Harden Traefik and the public edge

### Objective

Keep the only intended public service small, patched, observable, and unable to route unclaimed hosts.

### Actions

#### 16.1 Runtime

- Deploy the official chart as a DaemonSet.
- Run non-root with `readOnlyRootFilesystem: true`.
- Drop all capabilities and add only `NET_BIND_SERVICE`.
- Use `hostPort: 80/443`; avoid `hostNetwork`.
- Set resource requests/limits and high priority.
- Pin the chart and image digest.
- Roll one node at a time and verify `/ping`/readiness before proceeding.

#### 16.2 Management interfaces

- Disable `api.insecure`.
- Do not publish the dashboard/API.
- Use `kubectl port-forward` or a private authenticated route when troubleshooting.
- Keep metrics private and restrict scraping with NetworkPolicy/RBAC.

#### 16.3 TLS

- Set a minimum of TLS 1.2 unless a customer contract requires stricter settings.
- Enable strict SNI so unknown/unmatched certificate names do not receive a default tenant certificate.
- Keep the platform wildcard and stable origin certificate valid and attached.
- Test Cloudflare origin SNI explicitly before enabling strict SNI in SaaS.
- Alert on listener invalidity and certificate reference failures.
- Reject or return a neutral response for unknown HTTP Host values.

A Traefik TLSOption representation may look like:

```yaml
apiVersion: traefik.io/v1alpha1
kind: TLSOption
metadata:
  name: default
  namespace: edge-system
spec:
  minVersion: VersionTLS12
  sniStrict: true
```

The exact default-option namespace and Gateway integration are implementation-specific; verify them against the pinned Traefik version with real TLS tests.

#### 16.4 Forwarded headers and direct-origin access

- Keep `forwardedHeaders.insecure: false`.
- Trust `X-Forwarded-*` only from the actual Cloudflare/LB source CIDRs.
- Automate updates to trusted proxy ranges from the provider’s official list and review unexpected changes.
- In direct DNS mode, leave trusted proxy lists empty unless a known proxy exists.
- Where possible, restrict SaaS origin `80/443` to Cloudflare/LB networks or authenticate origin traffic. If customers also use direct platform hostnames, separate origin endpoints or carefully define the permitted direct path.
- Never trust a client-supplied `X-Forwarded-For` from the open internet.

#### 16.5 Abuse and resilience

- Configure sane header, body, read, write, idle, and keep-alive limits based on application requirements.
- Apply rate limits at Cloudflare for SaaS and/or Traefik for expensive endpoints.
- Limit retry amplification; do not blindly retry non-idempotent requests.
- Redact authorization, cookies, query secrets, and sensitive headers from access logs.
- Avoid high-cardinality route labels in Prometheus.
- Expose a lightweight edge health endpoint that does not depend on a tenant application.

### Verify

```bash
# Unknown SNI should fail or present no tenant certificate.
openssl s_client -connect <node-ip>:443 -servername unclaimed.invalid

# Known platform hostname should present the wildcard certificate.
openssl s_client -connect <node-ip>:443 \
  -servername clever-fox-21.templ-prod.supercompute.dev

# Test Host routing against each node directly.
curl --resolve clever-fox-21.templ-prod.supercompute.dev:443:<node-ip> \
  https://clever-fox-21.templ-prod.supercompute.dev/readyz
```

Also test malformed headers, slow clients, large bodies, WebSockets/HTTP2 if supported, and graceful edge pod termination.

---

## 17. Step 13 — Harden DNS, ACME, and customer-domain lifecycle

### Objective

Prevent certificate credential theft, failed renewals, and stale-domain takeover.

### Actions

#### 17.1 Platform wildcard

- Use a Cloudflare API Token, not the global API key.
- Grant only zone read and DNS edit for the platform zone.
- Store the token in a protected Secret created from Ansible Vault.
- Separate ACME staging and production issuers/accounts.
- Monitor Certificate, Order, and Challenge failures.
- Alert at 30, 21, 14, and 7 days before expiry, with escalation before 14 days.
- Test renewal in staging and force a controlled reissuance before launch.

#### 17.2 Self-host HTTP-01

- Keep port 80 reachable for the ACME challenge.
- Confirm HTTP-to-HTTPS redirect does not intercept or break the exact challenge route.
- Validate the Gateway listener permits cert-manager’s temporary HTTPRoute.
- Do not mark a custom domain ready merely because DNS resolves; require Certificate Ready and a successful HTTPS probe.

#### 17.3 SaaS custom domains

- Use Cloudflare for SaaS rather than an ordinary cross-account proxied CNAME.
- Prevalidate hostname/certificate ownership before cutover where the plan supports it.
- Treat both hostname status and certificate status as required readiness states.
- Use Full (strict) origin TLS.
- Keep fallback-origin and CNAME-target names stable.
- Health-check all origin nodes and remove failed origins from service.

#### 17.4 Ownership and offboarding

- Normalize and uniquely reserve every hostname.
- Require proof of control before public routing.
- Remove public routes before releasing ownership records.
- Keep tombstones and audit history.
- Scan for CNAMEs still targeting the platform but no longer claimed.
- Do not let deleted applications leave a reusable route or certificate reference.
- Consider CAA records for platform-owned zones, but plan changes carefully so they do not block the selected CA.

### Verify

Automate a complete onboarding/offboarding test with a disposable domain, including failed validation, certificate renewal, route deletion, and stale-CNAME detection.

---

## 18. Step 14 — Operate gVisor as an additional isolation tier

### Objective

Use gVisor where it materially reduces risk without pretending it removes the need for normal container controls.

### Actions

- Pin the gVisor release; do not install `latest` in production.
- Verify published checksums/signatures before installing `runsc` and its containerd shim.
- Install and smoke-test on every node intended to run sandboxed workloads.
- Create the `gvisor` RuntimeClass with a node selector so an unprepared node cannot receive the Pod.
- Keep tenant Pod Security, seccomp, non-root, capabilities, NetworkPolicy, and quotas enabled.
- Create an application compatibility suite covering languages, DNS, sockets, TLS, filesystems, process signals, probes, and observability.
- Measure CPU, memory, startup latency, syscall-heavy performance, and maximum density.
- Maintain a documented fallback to standard `runc` only after a risk decision; do not silently downgrade a requested sandbox.
- Alert when a Pod requesting gVisor is Pending because no compatible node is available.

### Verify

Inside a test Pod:

```bash
kubectl exec <gvisor-pod> -- dmesg | grep -i gvisor
```

Also inspect the container runtime and RuntimeClass status. Run cross-node rescheduling after stopping each node.

---

## 19. Step 15 — Secure the image supply chain

### Objective

Reduce the likelihood that a compromised or mutable image becomes cluster code execution.

### Actions

1. Build images in isolated CI, not on the production cluster nodes.
2. Use minimal base images and remove package-manager caches/build tools from runtime stages.
3. Run as a non-root fixed UID.
4. Never copy secrets, `.env` files, SSH keys, registry credentials, or cloud tokens into image layers.
5. Generate an SBOM for platform and customer-build images where supported.
6. Scan OS packages and language dependencies; define severity and exploitability thresholds.
7. Push to an approved registry with immutable tags.
8. Deploy by digest.
9. Sign platform release images and publish verification metadata.
10. Phase in admission signature enforcement only after emergency override and key rotation are tested.
11. Mirror critical platform images for self-host/offline customers and record source digests.
12. Monitor registry pull failures and rate limits.

### Pragmatic vulnerability policy

Do not promise “zero CVEs.” Require:

- no known actively exploited critical issue in a reachable component at release;
- remediation deadlines based on severity and exposure;
- documented exceptions when no patch exists;
- rapid rebuilds when base images update;
- customer-visible security advisories for affected self-hosted versions.

---

## 20. Step 16 — Protect data and persistent storage

### Objective

Make data durability and confidentiality explicit rather than assuming Kubernetes objects equal customer backups.

### Actions

- Keep application containers stateless by default.
- Prefer external database/object-storage services for hosted SaaS.
- Do not use hostPath or local-path storage for customer production data.
- Encrypt disks and backup destinations according to the hosting threat model.
- Use separate database credentials per application/tenant where practical.
- Rotate credentials without rebuilding images.
- Restrict database ingress by NetworkPolicy and database-side authentication.
- Never expose databases publicly for convenience.
- Define backup, retention, point-in-time recovery, and restore testing for every durable service.
- If a distributed CSI product is introduced, separately monitor replica health, rebuild traffic, snapshot status, backup target, and disk pressure.
- Test node replacement and volume attachment; do not infer durability from a “Bound” PVC alone.

### Verify

Restore a representative platform database and customer data set into a disposable environment. Confirm application-level consistency, not merely successful file extraction.

---

## 21. Step 17 — Centralize monitoring and logs

### Objective

Detect failures early and preserve evidence when a node is lost or compromised.

### Required alerts

#### Control plane and nodes

- etcd member down, quorum risk, high fsync latency, database growth;
- Kubernetes API not ready or elevated error/latency;
- node NotReady, reboot, clock drift, WireGuard handshake stale;
- CPU/memory/PID/disk/inode pressure;
- container runtime or CNI failure;
- unexpected public listening socket;
- failed security update or reboot backlog.

#### Edge and certificates

- Traefik pod unavailable on a DNS-listed node;
- elevated TLS handshake failures or `5xx` rate;
- unknown-host spikes and suspicious scanning;
- Gateway listener `Accepted/Programmed/ResolvedRefs` failures;
- certificate renewal failure or expiry threshold;
- Cloudflare/LB origin unhealthy;
- high connection count, body-size rejection, or rate-limit events.

#### Workloads and platform

- reconciliation queue backlog and repeated retries;
- applications unavailable or crash-looping;
- image pull failures;
- quota and admission denials;
- unusual Secret reads or RBAC changes;
- backup age, upload failure, or failed restore test.

### Logging rules

- Ship system, Kubernetes, Traefik, cert-manager, reconciler, and audit logs off-node.
- Use transport encryption and per-source authentication.
- Redact credentials, cookies, authorization headers, session tokens, query secrets, and sensitive environment values.
- Set retention intentionally; do not retain customer request content indefinitely by default.
- Protect logs from tenant write/read access.
- Synchronize timestamps and include node, cluster, tenant ID, application ID, and operation ID where safe.

### Verify

Run alert fire drills. An alert is incomplete until an operator receives it, can identify the affected component/customer, and can follow a linked action runbook.

---

## 22. Step 18 — Back up and prove disaster recovery

### Objective

Recover cluster state, platform state, and customer data using documented, tested artifacts.

### 22.1 What `k0s backup` covers

The k0s backup includes k0s-managed control-plane state such as PKI, the etcd snapshot, k0s configuration, managed manifests/image bundles, and Helm configuration. It does **not** back up application PersistentVolumes or every external database.

### 22.2 Backup schedule

- Daily k0s control-plane backup.
- Additional backup immediately before upgrades, controller replacement, encryption-key rotation, and major networking changes.
- Platform metadata database backups according to the published RPO.
- Separate application database/object/PV backups.
- Copy every backup off-cluster and off the node that created it.
- Encrypt backups; keep encryption recovery material separate.
- Use retention such as daily/weekly/monthly tiers based on business requirements.

Example on a controller:

```bash
sudo install -d -m 0700 /var/backups/k0s
sudo k0s backup --save-path=/var/backups/k0s
```

Validate the exact CLI for the pinned k0s release.

### 22.3 Backup security

A k0s backup contains highly sensitive PKI and cluster state. Treat it as a cluster-admin credential:

- owner root, mode `0600`/directory `0700`;
- encrypted before or during transfer;
- restricted backup destination identity;
- immutable/object-lock retention where practical;
- no ticket/email attachment;
- access logging and periodic restore access review.

Back up the Kubernetes EncryptionConfiguration key separately. An etcd backup without its encryption key may be unusable for Secrets; storing the key only inside the backup environment defeats recovery.

### 22.4 Restore drill

At least quarterly:

1. Provision disposable replacement nodes from Ansible.
2. Retrieve one selected backup and encryption key through the recovery process.
3. Restore the first controller on a clean data directory.
4. Join replacement controllers to re-form the three-member control plane.
5. Restore platform metadata and application data separately.
6. Verify nodes, API, etcd, routes, TLS, Secrets, and representative applications.
7. Run external HTTPS probes.
8. Record elapsed time, data loss relative to backup, failures, and corrective tasks.
9. Destroy the disposable environment securely.

Do not perform the first restore during a real outage.

---

## 23. Step 19 — Patch and upgrade safely

### Objective

Keep supported components current without sacrificing etcd quorum or application availability.

### Principles

- Pin versions; never let an omitted version silently select “latest.”
- Keep current on security patch releases after canary validation.
- Upgrade one Kubernetes minor at a time unless the exact supported path says otherwise.
- Take and export a backup before every cluster upgrade.
- Upgrade controllers one at a time and preserve quorum.
- Drain worker capacity rather than using `--no-drain`, except during a documented emergency.
- Combined controller/worker nodes need sufficient spare capacity for each drain.
- Kubernetes downgrade is generally not a normal rollback. Recovery may require restore/rebuild, so test before production.

### Procedure

1. Review release notes and security advisories for k0s/Kubernetes, Traefik, Gateway API, cert-manager, Calico, gVisor, and observability components.
2. Update a canary/self-host reference installation first.
3. Run API deprecation and CRD compatibility checks.
4. Verify backups and current etcd health.
5. Verify all three nodes Ready, no disk pressure, and enough capacity for one-node drain.
6. Verify PodDisruptionBudgets allow the intended operation.
7. Update `spec.k0s.version` and apply through k0sctl. k0sctl upgrades controllers one at a time and drains worker nodes as part of reconciliation.
8. Observe every node returning Ready before continuing.
9. Upgrade Gateway API CRDs, Traefik, cert-manager, and other add-ons only in the tested order.
10. Run the complete routing, TLS, NetworkPolicy, gVisor, and application smoke suite.
11. Keep the previous installer bundle and restore plan, not merely the old binary.
12. Promote to hosted SaaS and then supported self-host channels.

### Verify

- Kubernetes `/readyz` is healthy.
- etcd has three members and no alarms.
- every node runs the intended version.
- all Gateways/routes/certificates are accepted and ready.
- a two-replica application remains reachable throughout one node drain.
- no deprecated API or admission failure appears in logs.

---

## 24. Step 20 — Run k0s-specific security checks

### Objective

Use automated benchmarks as evidence and regression detection, not as a substitute for understanding the architecture.

### Actions

- Run the k0s-provided kube-bench profile for the pinned release.
- Track every failed or manually scored item.
- Classify findings as:
  - fixed;
  - not applicable;
  - accepted with compensating control;
  - scheduled.
- Re-run after k0s, Kubernetes, OS, or configuration upgrades.
- Add custom tests for controls not fully represented by the benchmark, especially:
  - encryption at rest;
  - audit policy and off-node shipping;
  - public firewall exposure;
  - Gateway/Traefik edge hardening;
  - tenant NetworkPolicy and PSS;
  - Ansible secret leakage;
  - backup/restore.

Example from the k0s documentation should be checked against the installed kube-bench package/profile:

```bash
kube-bench run \
  --config-dir <k0s-kube-bench-config-dir> \
  --benchmark k0s-1.0
```

A “100% benchmark pass” is not the goal if it requires controls that break the tested CNI or operations. The goal is an explained, reviewed, and continuously tested posture.

---

## 25. Step 21 — Prepare incident response and credential rotation

### Objective

Contain a compromised workload or node without inventing procedures during the event.

### 25.1 Compromised application

1. Disable/remove its public route.
2. Scale Deployment to zero or apply an isolation NetworkPolicy.
3. Preserve relevant logs, audit events, image digest, and Pod metadata.
4. Revoke application credentials and tokens.
5. Inspect other workloads using the same image or dependency.
6. Rebuild from a clean image; do not reuse a mutable compromised tag.
7. Restore data only after assessing persistence risk.

### 25.2 Suspected node root compromise

1. Remove the node’s public IP from the health-aware LB/DNS path where possible.
2. Block its WireGuard peer and management traffic at the other nodes/firewall.
3. Preserve provider console data, logs, disk snapshot, and audit evidence according to policy.
4. Assess etcd quorum before stopping services; avoid causing a second simultaneous loss.
5. Rotate credentials accessible from the node:
   - WireGuard key;
   - SSH host/admin credentials;
   - Kubernetes/k0s certificates or tokens as indicated;
   - registry/DNS/provider tokens present on the node;
   - application Secrets that ran there when the threat warrants it.
6. Replace the node from a clean image and Ansible; do not “clean and trust” it.
7. Rejoin etcd/control plane using the documented controller replacement procedure.
8. Review cluster-wide RBAC, audit events, workloads, and image state for persistence.

### 25.3 Lost etcd quorum

- Stop making ad hoc membership changes.
- Identify surviving healthy members and network state.
- Restore connectivity or replace one failed member using the k0s procedure.
- If recovery is not safe, restore from the latest verified backup to clean controllers.
- Communicate that existing traffic may differ from control-plane availability; do not claim recovery until reconciliation is healthy.

### 25.4 Certificate or DNS token compromise

- Revoke the provider token.
- Create a new narrow token and update the Secret through Ansible Vault.
- Review DNS audit logs and all zone records.
- Reissue affected certificates when private keys or ACME account keys may be exposed.
- Check for unauthorized custom hostname, origin, or validation changes.

### 25.5 Communications

Maintain:

- internal severity levels;
- incident commander and technical lead roles;
- customer notification criteria;
- status-page process;
- evidence-retention rules;
- post-incident review with tracked remediation.

---

## 26. Continuous validation suite

Run these tests after every meaningful infrastructure change and on a schedule.

### 26.1 External attack surface

```text
[ ] Only expected TCP/UDP ports reachable on every public IP.
[ ] Kubernetes API/kubelet/etcd/join API not reachable publicly.
[ ] Traefik dashboard/API not reachable publicly.
[ ] Unknown SNI and Host do not reach a tenant app.
[ ] Each DNS-listed node passes known-host HTTPS and edge health checks.
```

### 26.2 Identity and RBAC

```text
[ ] Anonymous API access rejected where configured.
[ ] Read-only operator cannot read Secrets or create Pods.
[ ] Reconciler can manage only intended resource groups/namespaces.
[ ] Tenant identity cannot create public routes, NodePorts, RBAC bindings, or privileged Pods.
[ ] Break-glass use generates an alert.
```

### 26.3 Workload isolation

```text
[ ] PSS rejects root/privileged/hostPath/hostNetwork/unsafe capability tests.
[ ] Default-deny blocks tenant-to-tenant and tenant-to-node traffic.
[ ] DNS and Traefik-to-app:8080 remain functional.
[ ] ServiceAccount token is absent from ordinary application Pods.
[ ] gVisor workload reschedules to another prepared node.
```

### 26.4 Reliability

```text
[ ] Stop one node: etcd quorum remains and HA application stays reachable.
[ ] Health-aware LB removes the failed node.
[ ] Drain one node: PDB/topology constraints permit maintenance.
[ ] Fill a test disk/memory limit: alerts and eviction behavior match runbook.
[ ] Restart Traefik on one node: other origins continue serving.
```

### 26.5 TLS and domains

```text
[ ] ACME staging issuance and renewal pass.
[ ] Platform wildcard certificate matches expected names.
[ ] Direct HTTP-01 challenge survives HTTP redirect configuration.
[ ] Cloudflare custom hostname reaches active/active status before readiness.
[ ] Deleted domain no longer routes and cannot be reclaimed without verification.
```

### 26.6 Recovery and upgrades

```text
[ ] Latest k0s backup is recent, encrypted, and present off-cluster.
[ ] Application/platform data backups meet RPO.
[ ] Restore drill within target RTO.
[ ] Canary upgrade completes and routing/security tests pass.
[ ] Encryption key rotation rehearsal succeeds.
```

---

## 27. Practical exception register

| Exception | Why it exists | Compensating controls | Review trigger |
|---|---|---|---|
| Combined controller/worker nodes | Three-node cost and simplicity | system reservations, quotas, priority, one-node-loss capacity test | sustained load, noisy-neighbor incidents, larger customer base |
| Traefik host ports 80/443 | Direct public DNS to every node | dedicated namespace, non-root, only `NET_BIND_SERVICE`, no hostNetwork, admission controls | edge redesign or external L4 LB adoption |
| Local encryption key on controllers | Avoid external KMS operational dependency at launch | Ansible Vault, mode 0600, off-cluster recovery copy, controller access controls | compliance request or controller-host threat increase |
| Cloudflare dependency for SaaS custom domains | Scalable certificate and hostname edge | provider-neutral self-host mode, origin TLS, exportable domain metadata | pricing/reliability or portability review |
| Plain multi-A DNS supported | Low-cost/self-host simplicity | documented lack of health awareness, application replicas, monitoring | paid SLA or customer availability requirement |
| Traefik CRD route adapter for large direct-TLS fleets | Gateway listener certificate aggregation limit | same product desired-state model, restricted controller ownership, compatibility tests | verified ListenerSet support or gateway redesign |

Exceptions without owners or review dates become permanent hidden risk. Keep this table in source control and include the deployed subset in self-host installation reports.

---

## 28. Ansible hardening implementation checklist

```text
roles/host_baseline
  [ ] dedicated admin user and SSH policy
  [ ] time synchronization
  [ ] tested sysctls/modules/cgroup/swap policy
  [ ] OS update and serial reboot logic
  [ ] filesystem/inode monitoring

roles/wireguard
  [ ] unique addresses and restricted AllowedIPs
  [ ] key material vaulted and mode 0600
  [ ] handshake monitoring
  [ ] no CIDR overlap

roles/firewall
  [ ] dedicated table/chain; never flush Kubernetes rules
  [ ] public port allow-list and explicit management drops
  [ ] WireGuard inter-node matrix
  [ ] NodePort range blocked
  [ ] validation from external and peer perspectives

roles/k0s
  [ ] pinned/verified k0s and k0sctl
  [ ] three controller+worker nodes, no single mode
  [ ] WireGuard privateAddress verification
  [ ] Calico and measured MTU
  [ ] node-local LB
  [ ] encryption and audit files mode 0600
  [ ] serial health-gated apply/upgrade

roles/gvisor
  [ ] pinned/verified binaries
  [ ] containerd drop-in
  [ ] RuntimeClass smoke test
  [ ] node label only after success

roles/cluster_addons
  [ ] pinned chart and image digests
  [ ] Gateway API compatibility matrix
  [ ] tenant PSS, quotas, policies, admission
  [ ] Traefik dashboard disabled and TLS policy validated
  [ ] cert-manager staging then production

roles/backup
  [ ] k0s backup schedule
  [ ] off-cluster encrypted transfer
  [ ] retention and failure alert
  [ ] platform/application data backup hooks
  [ ] restore-drill playbook

all secret tasks
  [ ] no_log: true
  [ ] diff: false
  [ ] no later debug of registered secret
  [ ] temporary plaintext mode 0600 and deleted
```

---

## 29. Controls intentionally not required at launch

The following may be valuable later, but making them launch blockers would add disproportionate complexity unless a customer or threat model requires them:

- external hardware-backed KMS;
- a service mesh for all application traffic;
- mutual TLS between every Pod;
- a separate cluster per ordinary tenant;
- mandatory gVisor for every workload;
- full egress domain filtering without an egress gateway;
- two independent DNS/CDN providers with automated failover;
- admission signature enforcement before signing operations are mature;
- a large SIEM deployment before useful audit/alert rules exist;
- a distributed storage layer for stateless launch workloads;
- continuous node forensics agents with broad host access and no operating owner.

Deferring these is a risk decision, not a claim that they have no value. Revisit them when workload hostility, customer contracts, compliance scope, or scale changes.

---

## 30. Final go-live checklist

```text
NETWORK
[ ] Public scan approved for all three node IPs.
[ ] Control-plane ports reachable only through WireGuard.
[ ] Firewall automation does not flush Kubernetes/CNI rules.
[ ] WireGuard peer and MTU tests pass.

IDENTITY AND SECRETS
[ ] Individual admin identities; bootstrap admin protected.
[ ] Ansible Vault IDs separated and recovery process tested.
[ ] Kubernetes Secret encryption enabled on all API servers.
[ ] Encryption key and k0s backups recoverable but separately protected.
[ ] Provider tokens narrowly scoped and rotated from any bootstrap defaults.

WORKLOAD ISOLATION
[ ] Tenant PSS restricted enforced at pinned version.
[ ] Admission rejects host access, NodePort, missing resources, and unapproved images.
[ ] Default-deny NetworkPolicy plus DNS/edge rules tested.
[ ] ResourceQuota/LimitRange applied to every tenant namespace.
[ ] ServiceAccount token automount disabled by default.
[ ] gVisor profile tested where offered.

EDGE AND TLS
[ ] Traefik non-root DaemonSet on 80/443; dashboard/API private or disabled.
[ ] Strict SNI/unknown Host behavior tested.
[ ] Trusted forwarded-header CIDRs correct for each environment.
[ ] Platform wildcard and origin certificate valid.
[ ] ACME renewal and custom-domain lifecycle tests pass.
[ ] Health-aware SaaS endpoint removes failed origin.

OPERATIONS
[ ] etcd three-member health and one-node failure test pass.
[ ] Off-node logs, metrics, audit, and actionable alerts operational.
[ ] Daily k0s backup and separate data backups current.
[ ] Restore drill and upgrade drill completed.
[ ] Incident isolation, credential rotation, and node rebuild runbooks exercised.
[ ] Security exceptions have owners and review dates.
```

---

## 31. Primary references

Pin version-specific pages for implementation and preserve the tested bill of materials.

### k0s

- Production installation with k0sctl: <https://docs.k0sproject.io/head/k0sctl-install/>
- High availability: <https://docs.k0sproject.io/head/high-availability/>
- Configuration reference: <https://docs.k0sproject.io/head/configuration/>
- Runtime and gVisor: <https://docs.k0sproject.io/head/runtime/>
- Verifying signed binaries: <https://docs.k0sproject.io/head/signature/>
- Backup and restore: <https://docs.k0sproject.io/head/backup/>
- Upgrade: <https://docs.k0sproject.io/head/upgrade/>
- k0s kube-bench profile: <https://docs.k0sproject.io/head/cis_benchmark/>
- Pod Security Standards in k0s: <https://docs.k0sproject.io/head/podsecurity/>

### Kubernetes security and operations

- Security checklist: <https://kubernetes.io/docs/concepts/security/security-checklist/>
- Pod Security Standards: <https://kubernetes.io/docs/concepts/security/pod-security-standards/>
- Pod Security Admission: <https://kubernetes.io/docs/concepts/security/pod-security-admission/>
- NetworkPolicy: <https://kubernetes.io/docs/concepts/services-networking/network-policies/>
- Encrypting confidential data at rest: <https://kubernetes.io/docs/tasks/administer-cluster/encrypt-data/>
- Auditing: <https://kubernetes.io/docs/tasks/debug/debug-cluster/audit/>
- RBAC good practices: <https://kubernetes.io/docs/concepts/security/rbac-good-practices/>
- Service accounts: <https://kubernetes.io/docs/concepts/security/service-accounts/>
- Resource management: <https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/>
- ResourceQuota: <https://kubernetes.io/docs/concepts/policy/resource-quotas/>
- LimitRange: <https://kubernetes.io/docs/concepts/policy/limit-range/>
- PodDisruptionBudget and disruptions: <https://kubernetes.io/docs/concepts/workloads/pods/disruptions/>
- Safely draining a node: <https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/>
- ValidatingAdmissionPolicy: <https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/>

### Edge, certificates, and automation

- Traefik Helm chart examples: <https://github.com/traefik/traefik-helm-chart/blob/master/EXAMPLES.md>
- Traefik API/dashboard security: <https://doc.traefik.io/traefik/reference/install-configuration/api-dashboard/>
- Traefik TLS options: <https://doc.traefik.io/traefik/reference/routing-configuration/http/tls/tls-options/>
- cert-manager HTTP-01: <https://cert-manager.io/docs/configuration/acme/http01/>
- cert-manager Cloudflare DNS-01: <https://cert-manager.io/docs/configuration/acme/dns01/cloudflare/>
- Cloudflare Full (strict): <https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/>
- Ansible Vault CLI: <https://docs.ansible.com/projects/ansible/latest/cli/ansible-vault.html>
- Ansible logging and `no_log`: <https://docs.ansible.com/projects/ansible/latest/reference_appendices/logging.html>
- gVisor production guide: <https://gvisor.dev/docs/user_guide/production/>

---

## 32. Closing position

For this platform, the highest-value controls are not exotic:

```text
private control plane over WireGuard
+ strict host firewall
+ patched and pinned k0s/edge components
+ least-privilege identity
+ encrypted Secrets
+ restricted tenant Pods
+ default-deny networking
+ resource quotas
+ narrow edge exception
+ automated TLS ownership checks
+ off-node logs and alerts
+ verified backups and practiced restores
+ serial, tested upgrades
```

Implement these consistently before adding sophisticated security products. A smaller set of controls that is automated, measured, and rehearsed is safer than a larger stack nobody can confidently operate during an outage.
