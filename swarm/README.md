# Docker Swarm template

This repository is a reusable Docker Swarm deployment template with two
inventory-parity profiles:

- `templ-local`: three project-owned Ubuntu 26.04 ARM64 Lima VMs connected by a
  project-managed WireGuard mesh, plus an independently managed local Garage
  S3-compatible service.
- `templ-prod`: three existing Ubuntu 26.04 AMD64 servers connected by a
  project-managed WireGuard mesh.

The public lifecycle is deliberately explicit. `lima-up` manages only the
template-local project VMs, `wg-*` manages only WireGuard, `swarm-*` manages the
three-node Docker Swarm, and `garage-*` manages the standalone Garage objects in
the existing shared Lima `default` profile.

Garage is provider-independent and uses one stable Docker namespace in that
shared profile: container and network `swarm-garage`, with volumes
`swarm-garage-data` and `swarm-garage-metadata`. Confirmed `garage-destroy`
removes these resources and recognized deployment-prefixed predecessors whose
Stackific ownership labels match their names.

Template-local commands set `LIMA_HOME` to the real, persistent provider home
`$HOME/.lima/.templ-local`. Keeping this path under Lima's short system home
avoids macOS's 104-byte Unix-socket limit. The hidden provider directory stays
isolated from instances managed through the default `$HOME/.lima` home; it is
not a symlink and does not disappear after a restart. See [Lima's home-directory
layout](https://lima-vm.io/docs/dev/internals/).

Run `task --list` for the authoritative command surface.

## Customer deployment name

`deployment.yml` is the single source for the customer-visible deployment
namespace:

```yaml
deployment_name: customer-name
encryption_at_rest: true
```

Set it to the customer's lowercase DNS-label-safe name before the first
deployment. The supported value is 1-32 characters, begins with a letter, and
contains only lowercase letters, digits, and hyphens. Ansible derives backup
unit names, runtime paths, temporary workload names and labels, and S3 object
prefixes from it. The supported task wrapper loads this file for every
playbook; do not duplicate the value in provider inventories.

The wrapper also derives `inventory_slug` from the selected directory under
`inventories/` (`templ-local` or `templ-prod`) and injects it into every
playbook. Inventory-scoped state and backup objects therefore use
`<deployment_name>/<inventory_slug>/...`; do not hardcode a provider slug in
those values or set `inventory_slug` in `deployment.yml`.

Treat the name as immutable after deployment. Changing it does not rename or
migrate existing systemd units, server files, Restic repositories, or
certificate objects; it selects a new namespace.

`encryption_at_rest` is the single deployment-wide switch for fscrypt-backed
business-data storage on all Swarm nodes. Keep it `true` to make
`/srv/secure` encrypted and require Docker to start only while that directory
is unlocked. Set it before placing data in `/srv/secure`; automation refuses
to encrypt existing plaintext data in place.

## Documentation map

- [Template-local setup](docs/setup-templ-local.md)
- [Template-production setup](docs/setup-templ-prod.md)
- [Add or remove a Swarm node](docs/node-lifecycle.md)
- [Node lifecycle Taskfile automation
  proposal](docs/node-lifecycle-automation-proposal.md)
- [Encrypted business-data storage](docs/encrypted-at-rest.md)
- [Networking](docs/networking.md)
