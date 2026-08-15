# Traefik and certificate management proposal

This proposal targets the reusable Docker Swarm template and both of its
inventory profiles.

Status: Proposed for review; not implemented  
Requirements source: [`request.md`](request.md)  
Last updated: 2026-08-14

## 1. Decision summary

For the hosted platform, run Traefik as a Docker Swarm global service on every active manager whose `run_on_backup` label is not `true`. In the current three-node topology this means the two public edge nodes. Publish TCP 80 and 443 in host mode, discover application services through the Swarm provider, and route every application to its internal port 8080.

Do not use Traefik's built-in ACME resolver in the multi-node hosted mode. Instead, build a small certificate control plane in Go using lego for ACME protocol operations. Run exactly one controller task with a node-local SQLite database and Litestream continuously replicating that database to S3-compatible object storage. Store immutable encrypted certificate bundles in the same object store under a separate prefix, and synchronize those bundles into a node-local certificate cache on every eligible edge. Traefik loads the cache through its watched file provider. A TLS handshake must never depend on SQLite, Litestream, the controller, or S3 being available.

Use these issuance methods:

- `*.templ-prod.supercompute.dev`: DNS-01 using a narrowly scoped credential for the platform DNS zone.
- Exact customer domains: HTTP-01, with the customer's DNS pointing to the public edge addresses and a challenge responder reachable through every edge.
- Customer wildcards: require `_acme-challenge` delegation, customer-provided DNS API credentials for a supported provider, or a customer-provided certificate. Wildcard issuance cannot be both automatic and DNS-provider-neutral without one of these arrangements.

Keep the third, backup-labelled manager active in the Swarm but exclude it from Traefik, the certificate controller, and ordinary application workloads. Its periodic Drain/Active backup transition must not affect public ingress or certificate operations.

For self-hosted installations, provide explicit simple, HA, and bring-your-own-certificate modes. For local development, use mkcert and an sslip.io development suffix while exercising the same Traefik file-provider and routing path used in production.

## 2. Goals

- Route a dynamically created application hostname to the matching Swarm service on internal port 8080.
- Serve the platform wildcard and arbitrary exact customer domains from every public edge.
- Keep existing HTTPS traffic working through a controller, database, or object-storage outage.
- Renew and distribute certificates without restarting Traefik.
- Preserve the repository's `run_on_backup` scheduling convention.
- Support hosted SaaS, portable self-hosted HA, simple single-node self-hosting, and local development.
- Make issuance idempotent, rate-limit aware, observable, and recoverable.
- Avoid storing routinely renewed certificate material as Docker Secrets.

## 3. Non-goals

- Implementing this proposal as part of its review.
- Choosing a public cloud, DNS vendor, or S3-compatible storage vendor.
- Making DNS round robin provide health-aware failover.
- Backing up application databases or volumes; those remain separate from Swarm-state and certificate-control-plane backups.
- Issuing an arbitrary customer wildcard without DNS control, challenge delegation, or customer-provided certificate material.
- Exposing application, controller, dashboard, metrics, or S3 ports publicly.

## 4. Existing constraints

This proposal builds on the current repository conventions:

- The cluster has three Docker Swarm managers connected by WireGuard.
- Swarm control and data-path traffic use the WireGuard addresses.
- All three managers are schedulable by default.
- Exactly one manager has `run_on_backup=true`; ordinary services use `node.labels.run_on_backup != true`.
- The backup manager is temporarily drained during the six-hour Swarm-state backup and returned to Active afterward.
- Docker uses the pinned gVisor `runsc` runtime with netstack by default.
- Images must be pinned by digest.
- template-production currently exposes two edge-node public addresses through DNS.

## 5. Proposed architecture

### 5.1 Component view

```text
                              public DNS
                  platform wildcard + customer domains
                                  |
                         round-robin A/AAAA
                           /              \
                          v                v
                +----------------+  +----------------+
Internet 80/443 | edge manager 1 |  | edge manager 2 |
--------------->| Traefik global |  | Traefik global |<---------------
                | local cert     |  | local cert     |
                | cache          |  | cache          |
                +-------+--------+  +--------+-------+
                        |                    |
                        +------ overlay -----+
                               network
                           /       |       \
                          v        v        v
                    app service  app ...  ACME HTTP
                       :8080               responder
                                               |
                                      +--------+---------+
                                      | certificate      |
                                      | controller       |
                                      | Go + lego        |
                                      +---+-----------+--+
                                          |           |
                                  local SQLite    Litestream
                                  metadata/jobs       |
                                                      v
                                                S3-compatible
                                                SQLite replica +
                                                encrypted bundles

                +-----------------------------------------+
                | backup manager 3                        |
                | run_on_backup=true                      |
                | no Traefik, controller, or normal apps  |
                +-----------------------------------------+
```

The two edge caches are independent copies. Losing one edge or rebuilding its cache does not alter the other. Neither Traefik instance talks to S3 during a request.

### 5.2 Request path

```text
client
  -> DNS selects one public edge IP
  -> that node's host-published Traefik :443
  -> Traefik selects a locally loaded certificate by SNI
  -> Host() router selects the application service
  -> Swarm overlay routes to an eligible task on port 8080
```

### 5.3 Certificate publication path

```text
single controller obtains/renews certificate
  -> validates key, chain, names, and expiry
  -> envelope-encrypts an immutable bundle
  -> uploads bundle to S3-compatible storage
  -> records the generation in local SQLite and publishes a signed current manifest
  -> Litestream continuously replicates SQLite changes to S3-compatible storage
  -> edge sync agents fetch and verify that generation
  -> each agent writes versioned local files
  -> each agent atomically replaces the watched dynamic TLS manifest
  -> Traefik reloads the certificate without a process restart
```

Traefik's file provider supports dynamic TLS certificate configuration. Its documentation recommends watching a directory and mounting the parent directory because atomic file replacement can break notifications when only a single file is bind-mounted. The implementation will therefore watch a directory, write versioned PEM files, and atomically replace a small manifest within that directory. See [Traefik's file-provider documentation](https://doc.traefik.io/traefik/reference/install-configuration/providers/others/file/) and [dynamic TLS configuration reference](https://doc.traefik.io/traefik/reference/dynamic-configuration/file/).

## 6. Traefik data plane

### 6.1 Service placement and publishing

Traefik will be a global Swarm service with these placement constraints:

```yaml
deploy:
  mode: global
  placement:
    constraints:
      - node.role == manager
      - node.labels.run_on_backup != true
```

A global service creates one task on every eligible active node. Draining an edge manager stops its Traefik task; returning it to Active recreates the task. The backup-labelled manager remains excluded. This follows Docker's [global-service behavior](https://docs.docker.com/engine/swarm/how-swarm-mode-works/services/) and [Drain behavior](https://docs.docker.com/engine/swarm/swarm-tutorial/drain-node/).

TCP 80 and 443 will be published in host mode. No application service will publish a host port. The provider firewall remains the Internet perimeter described by the hardening proposal.

### 6.2 Swarm discovery

Traefik will use the Swarm provider with:

- `exposedByDefault=false`;
- a named ingress overlay as the default network;
- labels under each service's `deploy.labels` section;
- an explicit backend port of 8080 for every application;
- no public dashboard or API;
- no `certResolver` label in hosted HA mode, because certificates come from the file provider.

A generated application service follows this contract:

```yaml
services:
  clever-fox-21:
    image: example.invalid/app@sha256:<digest>
    networks:
      - edge
    deploy:
      placement:
        constraints:
          - node.labels.run_on_backup != true
      labels:
        - traefik.enable=true
        - traefik.swarm.network=edge
        - traefik.http.routers.clever-fox-21.rule=Host(`clever-fox-21.templ-prod.supercompute.dev`)
        - traefik.http.routers.clever-fox-21.entrypoints=websecure
        - traefik.http.routers.clever-fox-21.tls=true
        - traefik.http.services.clever-fox-21.loadbalancer.server.port=8080
```

Names used in labels must be derived from an immutable application identifier and sanitized separately from the customer-visible hostname. The platform must reject duplicate hostname claims before deploying a router.

Traefik's official Swarm example places routing labels under `deploy`, recommends disabling default exposure, and sets the backend port explicitly. See the [Traefik Swarm setup](https://doc.traefik.io/traefik/v3.4/setup/swarm/).

### 6.3 Docker API access

Swarm discovery requires access to the manager API. Docker API access is root-equivalent, so an Internet-facing Traefik container should not receive an unrestricted Docker socket by default.

The preferred design is a dedicated, internal-only socket proxy with an allowlist limited to the read endpoints Traefik needs for Swarm discovery. The endpoint allowlist must be proven with integration tests before deployment. If the first implementation temporarily mounts the socket directly, that is an explicit reviewed exception; a read-only bind mount is not treated as a security boundary.

### 6.4 gVisor

Traefik remains on the repository's default `runsc` runtime and netstack unless testing proves an incompatibility that requires a documented exception. Acceptance testing must cover:

- host-mode publishing on 80 and 443;
- overlay routing to application tasks;
- access to the chosen Docker API proxy or socket;
- read-only bind mounting of the local certificate cache;
- TLS reload after an atomic manifest update;
- client source-address and forwarded-header behavior.

No runtime exception will be introduced silently.

## 7. DNS and edge availability

### 7.1 Hosted platform domains

The platform wildcard DNS record for `*.templ-prod.supercompute.dev` points to both public edge addresses. The wildcard certificate covers application subdomains such as `clever-fox-21.templ-prod.supercompute.dev`. If the apex `templ-prod.supercompute.dev` is served, it must be included as a separate certificate name because the wildcard does not cover the apex.

### 7.2 Customer domains

An exact customer hostname may use A/AAAA records for the edge addresses or a CNAME that ultimately resolves there. Before issuance, the controller verifies that all resolved public addresses belong to the installation's approved edge set. It repeats this validation before renewals and alerts on drift.

### 7.3 Round-robin limitation

DNS round robin is distribution, not health checking. If one edge is down or drained, DNS may continue returning its address and clients may fail until they retry another address. A low TTL does not correct already cached answers.

For hosted production, the recommended follow-up is a provider-neutral L4 load balancer or health-checked authoritative DNS in front of the edge nodes. Direct DNS remains a supported initial mode only if this degraded failure behavior is accepted and tested. This proposal does not select or implement that service.

## 8. Certificate control plane

### 8.1 Controller choice

Build a small Go controller using [lego](https://go-acme.github.io/lego/) as its ACME library. lego provides the ACME primitives, HTTP-01 and DNS-01 implementations, wildcard support, and many DNS-provider adapters. The controller supplies the product-specific behavior that lego does not:

- tenant and hostname authorization;
- issuance and renewal scheduling;
- idempotency and per-certificate locking;
- rate-limit handling and audit records;
- encrypted object publication;
- edge manifests and rollout status;
- customer-domain lifecycle and revocation policy.

Traefik's built-in ACME resolver is suitable for a single Traefik instance, but it is not the hosted HA design. Traefik documents multi-instance ACME challenge ownership as a problem and recommends a separate certificate controller in its multi-instance guidance. That documentation is written for Kubernetes; this proposal deliberately applies the same ownership and shared-state concern to multiple independent Swarm tasks instead of assuming Swarm makes it safe. See [Traefik ACME configuration](https://doc.traefik.io/traefik/reference/install-configuration/tls/certificate-resolvers/acme/).

### 8.2 Runtime shape

In hosted mode:

- Run exactly one controller task constrained by both `node.labels.cert_controller == true` and `node.labels.run_on_backup != true`.
- Set `cert_controller=true` on exactly one non-backup manager at a time.
- Expose no controller port publicly except the HTTP-01 path proxied by Traefik.
- Route the HTTP-01 path from either edge Traefik instance to the single controller over the private overlay.
- Run the controller and Litestream in one image, with Litestream supervising the controller through the complete configuration and command defined in section 8.3.
- Store the SQLite file on node-local persistent storage, never a network filesystem.
- Keep the controller off the backup-labelled manager so the scheduled backup drain cannot interrupt it.

The controller API and challenge responder may be one binary, but their handlers, authorization, rate limits, and metrics remain separate. If the controller is unavailable, existing HTTPS continues and only issuance, renewal, and domain changes pause.

### 8.3 SQLite and Litestream

The node-local SQLite database is authoritative for live operational state:

- tenants and hostname claims;
- domain validation results;
- certificate names and current generation;
- ACME orders and active challenges;
- renewal schedule and retry state;
- idempotency keys and in-process job claims;
- object checksums and publication status;
- edge acknowledgement state;
- audit events.

Exactly one controller process writes this database. Litestream is the continuous replication and restore layer; it does not replace SQLite and is not a multi-writer database. The controller must use WAL mode, a bounded `busy_timeout`, transactional uniqueness constraints, and an integrity check during startup.

The controller data directory is node-local. Pin Litestream `0.5.15` in the controller image and verify the architecture-specific artifact checksum during the image build. The image entrypoint renders `/run/sc-cert-controller/litestream.yml` into tmpfs with mode `0600`. The complete rendered configuration is:

```yaml
dbs:
  - path: /var/lib/sc-cert-controller/controller.sqlite
    replica:
      type: s3
      bucket: "{{ swarm_backup_s3_bucket }}"
      path: "{{ deployment_name }}/{{ provider }}/certificates/v1/controller/{{ installation_id }}/litestream"
      endpoint: "{{ swarm_backup_s3_endpoint }}"
      region: "{{ swarm_backup_s3_region }}"
      force-path-style: {{ 'true' if swarm_backup_s3_bucket_lookup == 'path' else 'false' }}
      skip-verify: false
      access-key-id: "{{ swarm_backup_s3_access_key }}"
      secret-access-key: "{{ swarm_backup_s3_secret_key }}"
```

The braces above identify values rendered by deployment automation; they are not literal Litestream syntax. The access key and secret are read from the existing backup Docker Secrets while rendering the tmpfs file and must never be printed. `swarm_backup_s3_require_https` is validated before rendering: template-production must use HTTPS; local Garage may use its configured private HTTP endpoint. `force-path-style` is `true` for Garage's `path` lookup mode and `false` otherwise.

Do not inherit the Swarm backup's six-hour schedule or 30-day retention policy. This configuration deliberately omits Litestream's snapshot, retention, monitoring, checkpoint, and synchronization timing overrides, so the pinned Litestream release controls continuous replication using its defaults. Snapshot retention is a separate point-in-time-recovery decision and must be introduced only after its recovery window and storage cost are explicitly accepted.

Litestream is PID 1 and supervises the controller. The complete container command is:

```sh
exec /usr/local/bin/litestream replicate \
  -config /run/sc-cert-controller/litestream.yml \
  -restore-if-db-not-exists \
  -log-level info \
  -exec "/app/certificate-controller serve --database /var/lib/sc-cert-controller/controller.sqlite --listen 0.0.0.0:8080"
```

All Litestream flags precede positional arguments as required. There are no positional database or replica arguments in this form because the database path and complete S3-compatible replica definition are in the rendered configuration. When the supervised controller exits, Litestream performs its shutdown synchronization and exits with it.

Startup behavior is deliberately explicit:

1. If the local SQLite file exists and passes integrity checks, reuse it and continue Litestream replication.
2. If the local file is absent and the remote replica exists, Litestream restores it before starting the controller.
3. If neither exists, initialize a new database only during an explicitly authorized first bootstrap for that installation.
4. If S3 is unreachable, credentials are invalid, or restore integrity fails, fail closed instead of initializing an empty production database.

Litestream documents `-restore-if-db-not-exists` and process supervision through `-exec`; its production guidance recommends configuration-file mode for retention and provider-specific options. See the [replicate command](https://litestream.io/reference/replicate/), [configuration reference](https://litestream.io/reference/config/), and [Docker deployment guidance](https://litestream.io/guides/docker/).

Automatic active-active failover is not part of this design. Before moving `cert_controller=true` to another manager, the operator or automation must fence the old controller and prove it cannot write. After failover, a returning node's stale SQLite file must be quarantined and restored from the current Litestream replica; it must not be reused. SQLite and Litestream remain on local storage and are never placed on NFS, SMB, GlusterFS, or another network filesystem. See SQLite's [appropriate-use guidance](https://www.sqlite.org/whentouse.html).

### 8.4 Object storage

S3-compatible storage is authoritative for durable certificate material and holds the Litestream replica, but it is not a coordination or locking service. Every certificate generation is an immutable encrypted object. SQLite records the current generation, and a signed manifest gives edge agents the object key and checksum.

Reuse the provider's existing Swarm-backup object-storage configuration: `swarm_backup_s3_endpoint`, `swarm_backup_s3_require_https`, `swarm_backup_s3_bucket`, `swarm_backup_s3_region`, `swarm_backup_s3_bucket_lookup`, `swarm_backup_s3_access_key`, and `swarm_backup_s3_secret_key`. Do not create a second bucket or a second S3 credential pair for the certificate control plane. Derive both prefixes from the single `deployment_name` in `deployment.yml`: certificates use `<deployment_name>/<provider>/certificates/v1`, while Swarm backups use `<deployment_name>/<provider>/swarm-state/v1`.

Suggested layout:

```text
<deployment_name>/<provider>/certificates/v1/bundles/<tenant-id>/<certificate-id>/<generation>/bundle.enc
<deployment_name>/<provider>/certificates/v1/manifests/<installation-id>/current.json
<deployment_name>/<provider>/certificates/v1/acme/accounts/<issuer>/<account-id>.enc
<deployment_name>/<provider>/certificates/v1/controller/<installation-id>/litestream/
```

Required storage contract:

- HTTPS endpoint and authenticated S3 API;
- read-after-write for a newly published object;
- atomic replacement of one manifest object;
- bucket versioning or an equivalent undelete/history feature where available;
- versioning and retention covering the certificate prefix;
- no reliance on S3 for distributed locks or multi-object transactions.

AWS S3 and Cloudflare R2 document strong per-object consistency, but concurrent writes are still last-writer-wins and multiple keys do not form a transaction. The single local controller owns coordination; S3 must never be used to elect or fence a writer. See the [Amazon S3 consistency model](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html) and [Cloudflare R2 consistency model](https://developers.cloudflare.com/r2/reference/consistency/).

### 8.5 Encryption and credentials

Certificate bundles and ACME account keys are application-envelope-encrypted before upload. Provider-side encryption is additional defense, not a replacement. Each object records its encryption-key identifier, nonce, plaintext checksum, certificate names, and generation inside authenticated metadata.

The object-store credential is deliberately shared with the existing Swarm backup configuration:

- the controller, Litestream, and edge sync agents use the values already supplied through the seven `swarm_backup_s3_*` variables named above;
- the existing bucket is reused, while Swarm backups and certificate data occupy non-overlapping prefixes;
- no `certificate_s3_bucket`, certificate-specific access key, or certificate-specific secret key is introduced;
- this prefix separation prevents naming collisions but is not an IAM security boundary, so bucket versioning and restore testing remain required;
- platform DNS-01 credential: limited to the required challenge records if the DNS provider supports that scope;
- customer DNS credentials, when accepted: encrypted per tenant, narrowly scoped, and never placed in application containers.

Controller bootstrap credentials are injected as Docker Secrets. These include the existing backup S3 access-key and secret-key values, platform DNS token, optional ACME External Account Binding credential, and the reference or key needed to decrypt certificate bundles. The S3 endpoint, bucket, region, bucket-lookup mode, and certificate prefix are non-secret configuration. The container creates Litestream's runtime configuration in tmpfs from those inputs; credentials are not embedded in the image or tracked configuration. The ACME account private key is mutable durable state and is stored as an encrypted object, not as a rotating Docker Secret. The same Vault-backed S3 values and the bundle decryption key are rendered for the host sync agent into root-owned `0600` files because the sync agent is a systemd service, not a Swarm task. The Vault password file is only the key that decrypts Ansible Vault; it is not itself the restic password, S3 secret, or certificate encryption key.

Docker Secrets are appropriate for relatively static bootstrap credentials because Swarm stores them in encrypted Raft and mounts them into tasks through an in-memory filesystem. They are not appropriate for each renewed certificate because a Docker Secret is immutable and rotation requires a new secret name plus service update. See [Docker Secrets](https://docs.docker.com/engine/swarm/secrets/).

## 9. Edge certificate synchronization

Install a `sc-traefik-cert-sync` systemd service on every manager whose inventory setting resolves to `run_on_backup=false`. Do not install or enable it on the backup-labelled node.

The agent:

1. Polls the signed current manifest every 30 seconds with jitter, with an optional event-triggered wake-up later.
2. Downloads only a generation it does not already have.
3. Authenticates and decrypts the bundle.
4. Verifies checksum, key/certificate match, chain, allowed hostname set, and validity window.
5. Writes to a new generation directory with restricted ownership and permissions.
6. Generates the complete Traefik dynamic TLS manifest.
7. Atomically replaces the manifest within the watched parent directory.
8. Confirms locally that Traefik serves the expected fingerprint and expiry.
9. Reports its applied generation to the controller.
10. Retains the last known-good generation for rollback and removes older local generations after a short retention period.

Proposed host layout:

```text
/var/lib/<deployment_name>/traefik-certs/
  releases/<generation>/cert.pem
  releases/<generation>/key.pem
  dynamic/tls.yml
```

Traefik receives the parent directory as a read-only mount. The private-key files are never world-readable. The sync agent owns writes; Traefik cannot mutate the store.

If an update is corrupt or incomplete, the agent leaves the current manifest untouched. If S3 is unavailable, the agent retains the last known-good cache and retries. Existing TLS handshakes continue because Traefik already has the active certificate configuration locally.

## 10. Issuance flows

### 10.1 Platform wildcard

Use DNS-01 for `*.templ-prod.supercompute.dev` because ACME wildcard certificates require DNS-01. Include `templ-prod.supercompute.dev` as another SAN only if the apex is served.

Flow:

1. A scheduled controller job acquires the certificate lease.
2. lego creates the ACME order.
3. The controller creates the required `_acme-challenge` TXT record using the scoped platform credential.
4. It waits for authoritative DNS propagation and completes validation.
5. It removes the challenge record when safe.
6. It validates, encrypts, and publishes the certificate generation.
7. Both edge agents install it and acknowledge the served fingerprint.

### 10.2 Exact customer hostname

Use HTTP-01 so the customer does not have to provide DNS API credentials.

Flow:

1. The tenant claims an exact hostname.
2. The controller normalizes IDNA, enforces public-suffix and reserved-name rules, and rejects a hostname already owned by another tenant.
3. The controller checks that DNS resolves only to approved edge addresses.
4. lego creates the order and the controller stores the exact Host, token, key authorization, and expiry in SQLite.
5. Every Traefik edge has a fixed, high-priority HTTP router for `/.well-known/acme-challenge/` that forwards to the replicated responder over the overlay network.
6. The responder returns a value only for the exact active Host and token; all other requests return 404.
7. The controller completes issuance and publishes the new generation.

HTTP-01 must be reachable on TCP 80 and cannot issue wildcard certificates. When a hostname resolves to multiple web servers, the challenge response has to work through all of them. See Let's Encrypt's [challenge-type documentation](https://letsencrypt.org/docs/challenge-types/).

Certificate issuance never happens synchronously during a TLS handshake. Until a hostname is validated and its certificate is acknowledged by the required edges, the application stays in a pending-domain state rather than receiving an unrelated default certificate.

### 10.3 Customer wildcard

Offer three explicit choices:

- Recommended: the customer delegates `_acme-challenge.<domain>` by CNAME or NS to a platform-controlled validation zone.
- Supported provider integration: the customer supplies a narrowly scoped DNS API credential supported by lego.
- BYO certificate: the customer uploads a valid certificate and matching private key through an authenticated control-plane API.

The product must not imply that an arbitrary wildcard can be issued using only A/AAAA records. DNS-01 is mandatory for wildcards, and credential storage adds a larger security obligation.

### 10.4 Bring-your-own certificate

Before accepting a BYO bundle, the controller verifies:

- the private key matches the leaf certificate;
- the chain parses and is ordered correctly;
- the requested hostnames are covered;
- the leaf is currently valid and has an acceptable remaining lifetime;
- the key algorithm and strength meet policy;
- the tenant controls the hostname through the same ownership workflow.

The accepted bundle then uses the same encryption, publication, synchronization, observation, and expiry-alert path as an ACME-issued certificate.

## 11. Renewal and rollback

The scheduler evaluates certificates at least hourly. It uses ACME Renewal Information when supported by the selected lego version and CA, with a policy-based renewal window as fallback. It must not create an order on every application deployment or every scheduler pass.

For each renewal:

1. Claim the renewal job transactionally in SQLite using its normalized certificate name set and idempotency key.
2. Recheck tenant ownership, DNS destination, CAA, and current certificate state.
3. Renew through the configured challenge method.
4. Upload a new immutable encrypted generation.
5. Publish the generation only after upload and validation succeed.
6. Wait for edge acknowledgements and verify the served certificate on every required edge address.
7. Retain the prior object permanently under object-store retention policy and locally for at least seven days.
8. Roll the manifest back to the prior generation if post-publication validation fails.

Respect ACME `Retry-After`, use exponential backoff with jitter, and cap attempts. Use the CA staging environment in development and end-to-end tests. Let's Encrypt recommends staging for testing and publishes account, certificate, and failed-validation limits; see its [rate-limit documentation](https://letsencrypt.org/docs/rate-limits/).

## 12. Deployment modes

### 12.1 Hosted SaaS mode

- Global Traefik on all non-backup edge managers.
- One certificate-controller task pinned to the designated non-backup controller manager.
- Node-local SQLite for metadata, jobs, and audit state.
- Litestream for automatic restore and continuous SQLite replication to S3-compatible storage.
- S3-compatible object storage for encrypted immutable bundles.
- DNS-01 for the platform wildcard.
- HTTP-01 for exact customer hostnames.
- Delegated DNS-01, supported DNS credentials, or BYO for customer wildcards.
- A host sync agent on every eligible edge.

This is the primary design in this proposal.

### 12.2 Self-hosted simple mode

For a single Traefik instance, allow Traefik's built-in ACME resolver with one durable, backed-up `acme.json`. This mode is intentionally not HA and must reject a configuration that scales Traefik above one replica.

An alternative single-node parity option runs the same controller with local SQLite and Litestream targeting the operator's S3-compatible storage. SQLite remains local to that controller and is never shared over NFS. This option is useful when the operator needs the customer-domain API or expects to migrate to the multi-node mode.

### 12.3 Self-hosted HA mode

Use the hosted architecture, but require the operator to supply:

- an S3-compatible bucket meeting the storage contract;
- ACME issuer configuration;
- DNS credentials only for zones where DNS-01 is desired;
- an envelope-encryption key and backup policy.

The installation still runs one explicitly fenced controller writer with SQLite and Litestream. Traefik is highly available, while certificate issuance is active-passive: a controller outage does not interrupt existing TLS, but issuance and renewal pause until the controller is restored or safely moved.

The software must not depend on Stackific-owned DNS, S3, KMS, or ACME accounts. Endpoint, bucket, region, path-style behavior, CA bundle, and credential source are configuration.

### 12.4 Bring-your-own-certificate mode

Disable ACME issuance and import certificates through the controller. Multi-node installations still use SQLite, Litestream, S3, and edge synchronization. A simple single-node installation may use a protected local directory instead.

### 12.5 Local development mode

Use mkcert to create a locally trusted certificate for a suffix such as `*.127-0-0-1.sslip.io`. Generate application hostnames such as `clever-fox-21.127-0-0-1.sslip.io` and install the certificate through the same local cache and Traefik file-provider layout.

Local mode keeps these behaviors aligned with production:

- Host-based Traefik routing;
- application port 8080;
- global/inverse-backup placement conventions where applicable;
- file-provider certificate reload;
- no certificate lookup during a request.

It intentionally replaces public ACME, public DNS, Litestream's remote replica, and S3 with mkcert and local state.

## 13. Backup and recovery

The existing six-hour restic backup of `/var/lib/docker/swarm` protects encrypted Swarm Raft state, including Docker Secrets. It does not by itself protect the node-local SQLite file, Litestream replica, certificate bucket, envelope-encryption key, or application data.

Back up these layers separately:

| Layer | Required protection | Restore role |
|---|---|---|
| Swarm Raft | Existing encrypted restic schedule and tested restore | Service definitions and Docker Secrets |
| SQLite | Node-local persistent storage plus startup integrity checks | Live hostname ownership, orders, schedules, audit, current-generation metadata |
| Litestream replica | Continuous replication, retention, validation, and restore testing | Point-in-time recovery of the SQLite database on the controller node or a replacement |
| Certificate prefix in the existing backup bucket | Versioning plus tested prefix restore | Certificate and ACME-account material |
| Envelope key | Offline or separately controlled escrow, represented in Ansible Vault inventory by reference or sealed value | Decrypts restored bundles |
| DNS/API credentials | Ansible Vault or external secret manager with rotation procedure | Reissues DNS-01 certificates |
| Edge caches | No authoritative backup required | Rebuilt from the bucket after validation |
| Application data | Application-specific backup | Outside this proposal |

Object versioning is useful protection against accidental overwrite or deletion, but it is not an independent backup when the same principal can remove every version. AWS documents versioning as a data-protection mechanism; see [Amazon S3 data protection](https://docs.aws.amazon.com/AmazonS3/latest/userguide/DataDurability.html).

### 13.1 Rebuild one edge

1. Restore the node and its WireGuard identity through the existing operator procedure.
2. Reinstall the pinned Docker, gVisor, Traefik, and sync-agent versions.
3. Restore the provider's existing Vault-backed backup S3 credential and the certificate decryption material.
4. Synchronize and validate the current manifest and all referenced bundles.
5. Start Traefik and verify the expected certificate fingerprint through that node's public IP.
6. Only then add the IP to public DNS or declare the edge healthy.

### 13.2 Restore the certificate control plane

The minimum recoverable set is:

- Litestream's SQLite replica and its retention history;
- certificate-bucket backup and object versions;
- ACME account material;
- envelope-encryption key;
- controller bootstrap secrets;
- installation and edge identifiers.

Fence any prior controller writer, restore SQLite from Litestream to clean node-local storage, run integrity checks, and verify cross-referenced generations and checksums in object storage. Then start the single controller without issuance enabled, rebuild edge caches, and re-enable issuance after a dry-run audit. A recovery drill must prove that an existing certificate can be served and a staging certificate can be renewed.

## 14. Failure behavior

| Failure | Expected behavior | Required alert/action |
|---|---|---|
| S3 unavailable | Existing HTTPS continues from local caches; publication and new-edge hydration pause | Alert on sync failures and certificate expiry margin |
| Litestream replication unavailable while local SQLite is healthy | Existing HTTPS continues; the controller may retain local state, but new certificate publication pauses and replication lag grows | Restore S3 access before the local durability margin is threatened |
| Controller unavailable | Existing HTTPS continues; issuance, renewal, and domain changes pause | Restore the pinned controller or fence it before moving ownership |
| Controller moved without fencing the old writer | Split-brain risk; two divergent SQLite histories could be produced | Prevent through operational fencing; stop issuance and recover one authoritative history |
| One edge sync agent fails | That edge serves its last known-good generation | Alert on generation skew and stale sync time |
| Invalid new bundle | Agent rejects it and retains current manifest | Mark generation failed; investigate; no Traefik restart |
| One edge is drained/down | Its global Traefik task stops; the other edge continues | DNS may still send clients to failed IP; use health-aware front door or accept degradation |
| Backup node is drained | No ingress/controller impact | Backup proceeds and node returns Active with label unchanged |
| Object deleted accidentally | Current caches continue temporarily | Recover object version/backup before a node rebuild or renewal requires it |
| Envelope key lost | Existing loaded certs may serve, but durable bundles cannot be restored | Treat as disaster; key escrow is mandatory |

## 15. Security requirements

- Use digest-pinned images and pinned Go module versions.
- Keep 2377/TCP, 7946/TCP+UDP, and 4789/UDP off public interfaces.
- Publish only 80/TCP and 443/TCP for Traefik.
- Keep the Traefik dashboard and controller administration API private.
- Treat Docker API access as root-equivalent and prefer a proven allowlisted proxy.
- Do not place TLS private keys, DNS credentials, or S3 credentials in labels or environment variables.
- Keep certificate objects under `<deployment_name>/<provider>/certificates/v1`, never under the Swarm-state backup prefix.
- Restrict plaintext local key files by owner, group, and mode; erase them during node decommissioning.
- Redact tokens, private keys, ACME authorizations, and customer credentials from logs and traces.
- Authorize hostname ownership before routing or issuance, and record an audit event for every change.
- Validate CAA before first issuance and renewals.
- Apply tenant and installation rate limits before contacting the CA.
- Keep the HTTP-01 responder exact-host and exact-token only, with short expirations.
- Prefer `_acme-challenge` delegation over retaining broad customer DNS credentials.
- Continue to restrict administrative SSH at the hosting-provider firewall.

## 16. Observability

Expose internal metrics and structured events for:

- certificate expiry time and renewal window;
- controller order attempts, results, latency, and ACME rate-limit responses;
- active challenge count and rejected challenge requests;
- manifest generation and age;
- per-edge applied generation, last successful sync, and served fingerprint;
- stuck or duplicate controller jobs;
- SQLite integrity, Litestream replication lag, last successful snapshot, and restore validation;
- object-store availability;
- DNS destination drift;
- Traefik task count versus eligible edge count;
- public probes to each edge IP for representative platform and customer hostnames.

Alert at multiple expiry thresholds, for example 21, 14, and 7 days, and page before the shortest threshold. Generation skew between edge nodes is an alert even when the old certificate remains valid.

## 17. Verification and acceptance criteria

Implementation is accepted only when automated verification demonstrates all of the following:

- The current template-production cluster has exactly one Traefik task on each of the two `run_on_backup!=true` managers and none on the backup-labelled manager.
- The certificate controller and ordinary test workload also exclude the backup-labelled manager.
- Every generated application routes through Traefik to internal port 8080 and publishes no application host port.
- Swarm control/data ports are unreachable through each public address.
- The expected platform wildcard is served from both edge public IPs.
- An exact customer-domain staging certificate can complete HTTP-01 regardless of which edge receives the challenge.
- An S3 outage does not interrupt existing TLS traffic.
- A Litestream/controller outage does not interrupt existing TLS traffic.
- Startup reuses a valid local SQLite file without downloading or overwriting it.
- Startup with no local SQLite file restores the latest valid database through Litestream before starting the controller.
- A returning stale controller node is refused after failover until its local database is quarantined and restored.
- No test can run two controller writers simultaneously against one installation prefix.
- A new valid generation appears on every required edge and is served without restarting Traefik within two minutes of publication.
- A corrupt bundle is rejected and the prior certificate remains served.
- Draining and reactivating the backup node does not change Traefik or controller task counts.
- Draining one edge demonstrates both Swarm rescheduling behavior and the documented direct-DNS failure mode.
- gVisor netstack is the effective runtime for the Traefik and temporary verification workloads unless a reviewed exception exists.
- A rebuilt edge can hydrate its cache and serve the expected fingerprint without reissuing the certificate.
- A full staging recovery restores SQLite through Litestream, certificate material, and issuance capability from backups.
- Logs and `docker service inspect` expose no private keys or secret values.

## 18. Proposed delivery sequence

No phase starts until the preceding phase's acceptance checks pass.

1. Local routing: digest-pinned Traefik, Swarm labels, port 8080 contract, mkcert, sslip.io, and file-provider reload.
2. Hosted platform wildcard: one Go/lego controller, SQLite schema, Litestream replication, encrypted S3 bundles, sync agents, and DNS-01.
3. Exact customer domains: ownership state machine, DNS checks, replicated HTTP-01 responder, staging issuance, and audit events.
4. Customer wildcard and BYO: challenge delegation, supported DNS integrations, import validation, and credential lifecycle.
5. Recovery and HA: edge rebuild, Litestream point-in-time restore, fenced controller move, object restore, failure injection, rate-limit testing, and production rollout.

Each phase must pin artifacts by digest or checksum and include rollback instructions before production use.

## 19. Decisions requested before implementation

1. Accept direct DNS round robin's degraded failure behavior for the first release, or require a health-aware front door before production.
2. Confirm the controller-node fencing and label-move procedure for active-passive recovery.
3. Confirm customer wildcard priority: delegated `_acme-challenge`, selected customer DNS integrations, BYO only, or a phased combination.
4. Select a portable envelope-key backend and escrow procedure.
5. Decide whether the first release requires the Docker socket proxy or permits a time-bounded direct-socket exception after review.
6. Confirm that simple self-hosting may use built-in Traefik ACME, while multi-node self-hosting uses the single SQLite/Litestream controller.
7. Confirm the two-minute certificate propagation target, Litestream recovery-point target, and seven-day local certificate rollback retention.

## 20. Answers to the requirements questions

1. **Run one Traefik per eligible node?** Yes. Use a global service constrained to managers with `run_on_backup != true`.
2. **What happens when an eligible node is drained?** Its global Traefik task stops; when the node returns to Active, Swarm recreates the task. Direct DNS may still send clients to the drained node's public IP.
3. **What acts as the certificate controller?** In hosted and self-hosted multi-node modes, one pinned Go service using lego, local SQLite, Litestream, and S3-compatible storage.
4. **Custom software or an existing component?** A narrow custom controller around the existing lego ACME library. The custom part is limited to tenant authorization, job coordination, durable publication, synchronization state, and product APIs.
5. **How are certificates issued?** The platform wildcard uses DNS-01. Exact arbitrary customer domains use HTTP-01. Customer wildcards require delegated DNS-01, supported customer DNS credentials, or BYO certificates.
6. **Where are certificates stored?** Local SQLite stores live coordination and metadata. Litestream and immutable encrypted certificate material reuse the inventory's existing backup endpoint, credentials, bucket, region, and lookup mode under `<deployment_name>/<inventory_slug>/certificates/v1`; each edge has a disposable local cache.
7. **How are certificates synchronized?** A systemd sync agent on every eligible edge verifies versioned bundles and atomically updates Traefik's watched file-provider directory.
8. **Does S3 participate in a TLS handshake?** No. Traefik serves locally loaded certificates; S3 is only for durable storage and synchronization.
9. **What uses Docker Secrets?** Relatively static controller bootstrap credentials. Renewed certificates, customer keys, ACME account keys, and their metadata use the encrypted object/database/cache path.
10. **How does this fit the six-hour Swarm backup?** The Swarm backup protects service definitions and Docker Secrets in Raft under `<deployment_name>/<provider>/swarm-state/v1`. Litestream and certificate objects reuse that backup's S3 configuration and bucket but use `<deployment_name>/<provider>/certificates/v1`; the envelope key and DNS credentials still require protection, and edge caches are disposable.
11. **How is this packaged for SaaS and self-hosting?** SaaS and multi-node self-hosting use one fenced SQLite/Litestream controller; simple one-node installations may use built-in Traefik ACME; BYO-only is a separate supported mode.
12. **How is local/production parity preserved?** mkcert and sslip.io feed the same Traefik file-provider, Host-routing, Swarm-label, and internal-port-8080 model while replacing public ACME and external storage.
