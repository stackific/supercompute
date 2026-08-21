# Local setup

The `local` and `cust-local` providers run Ubuntu 26.04 ARM64 virtual machines
with Lima on Apple Silicon. The `prod` provider uses Ubuntu 26.04 AMD64 images
from its VPS provider. All three inventories have the same layout.

## Prerequisites

- macOS on Apple Silicon
- [Task](https://taskfile.dev/installation/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [Lima](https://lima-vm.io/docs/installation/)

Confirm that the host tools are available, then install the locked Ansible
environment:

```sh
task --version
uv --version
limactl --version
task setup
```

`task setup` checks that `uv.lock` is current, rejects any dependency artifact
without a SHA-256 pin, creates `.venv` from that lock, and verifies the installed
Ansible command. It does not install or change host software.

## Local Lima VMs

`local` and `cust-local` own Ubuntu 26.04 ARM64 VMs under a short, persistent
provider Lima home outside the repository:

```text
~/.lima/.<deployment_name>-<provider>
```

For this template that resolves to `~/.lima/.templ-cluster-local` or
`~/.lima/.templ-cluster-cust-local`. The path stays under Lima's system home so
macOS Unix-socket paths stay under the 104-byte limit, remains a real directory
with mode `0700`, and stays isolated from the shared `default` Lima profile.

Create or start the inventory VMs:

```sh
task lima-up PROVIDER=local
```

`lima-up` sets `LIMA_HOME` to that provider home, creates it when needed, checks
the longest expected `ssh.sock.*` path for every declared deployment host, and
creates each missing host from a tracked Lima definition under
`.state/<provider>/lima/`. That definition pins `provider.resources` (1 CPU,
2 GiB RAM, 5 GiB disk), disables containerd and mounts, attaches `user-v2` with a
stable MAC, and forwards guest UDP `51830` to a per-host loopback port so
WireGuard can reach the VM. Existing instances are only started; their CPU,
memory, disk, networks, and port forwards are not rewritten. If an existing VM
does not match the tracked contract, destroy and recreate it before `wg-up`.

Show the provider Lima home and instance status without creating state:

```sh
task lima-status PROVIDER=local
```

`lima-status` runs through Ansible and prints a resource table with allocated
CPUs, MEMORY, and DISK plus guest `RAM_FREE` and `DISK_FREE` for running VMs.

Destroy those VMs and their disks:

```sh
task lima-destroy PROVIDER=local CONFIRM=destroy-lima-local
```

Read-only helpers must call `scripts/lima-runtime-home.sh <provider> path` or
`existing` so they never create the directory. Mutating commands use `ensure`.

## WireGuard mesh (Lima providers)

`local` and `cust-local` share the same WireGuard Task surface. Production
(`prod`) is refused until the next slice.

| Command | Purpose |
| --- | --- |
| `task wg-up PROVIDER=local` | Install guest `wg0`, bring up the Mac controller, lockdown INPUT |
| `task wg-status PROVIDER=local` | Show controller and guest WireGuard peers |
| `task wg-ssh PROVIDER=local NODE=local-1` | SSH to a node over the mesh |
| `task wg-remove PROVIDER=local` | Tear down lockdown and controller mesh state |

`wg-up` ensures Vault WireGuard key pairs (`macos` plus each deployment host),
verifies Lima membership, bootstraps guests through ordinary Lima access, then
applies a fail-closed nftables INPUT policy:

- Allow TCP 22 on `wg0` from the Mac controller address
- Deny new TCP 22 on `eth0` after bootstrap (established Lima SSH may drain)
- Allow UDP `51830` on `eth0` from the Lima user-v2 subnet
- Allow TCP `80` and `443` inbound
- Outbound remains unrestricted

Addressing (do not overlap `local` and `cust-local` on one Mac without these
disjoint ranges):

| Provider | Mac | Nodes | Host UDP forwards |
| --- | --- | --- | --- |
| `local` | `10.79.0.1` | `10.79.0.11–13` | `51921–51923` → guest `51830` |
| `cust-local` | `10.79.1.1` | `10.79.1.11–13` | `51931–51933` → guest `51830` |

Controller state lives under `.state/<provider>/wireguard/` (gitignored). Guests
created before UDP forwards existed must be destroyed and recreated:

```sh
task wg-remove PROVIDER=local
task lima-destroy PROVIDER=local CONFIRM=destroy-lima-local
task lima-up PROVIDER=local
task wg-up PROVIDER=local
```

Ensure keys without bringing the mesh up:

```sh
task vault-wireguard-ensure PROVIDER=local
```

## Provider vaults

Initialize local access to a provider vault:

```sh
task vault-init PROVIDER=local
```

Vault initialization generates a new password automatically in the selected
provider's `inventories/<slug>/.vault-pass`. Every provider has its own password,
including `prod`, and the command never prompts for one.

Initialization is allowed only when the provider has no encrypted vault. If the
vault already exists, the command fails without changing the vault or its
password. Use `vault-edit`, `vault-reset`, or `vault-destroy` for an initialized
provider.

Edit a vault:

```sh
task vault-edit PROVIDER=prod
```

The edit command decrypts into a mode-`0600` temporary file, opens `$VISUAL`,
then `$EDITOR`, or `vi`, validates the YAML and provider identity, and atomically
syncs the encrypted result back to the inventory. Invalid edits leave the
existing encrypted vault unchanged.

`PROVIDER` is discovered from the directory name. Any immediate
`inventories/<slug>` directory containing `hosts.yml` is available to all vault
tasks without changing a Taskfile or script.

The deployment namespace comes from `deployment_name` in `deployment.yml`.
Vault IDs, encrypted vault identity, and temporary paths combine that value with
the discovered inventory slug. Each generated `.vault-pass` has mode `0600` and
is ignored by Git. Commit each encrypted provider `vault.yml`; never commit a
`.vault-pass`. On another computer, restore the matching provider's
`inventories/<slug>/.vault-pass` before initializing or editing its existing
vault.

Resetting a vault permanently replaces only that provider's contents with an
empty vault and generates a new password for that provider. Other provider
vaults and passwords are unchanged. The provider-specific confirmation is
required:

```sh
task vault-reset PROVIDER=local CONFIRM=reset-vault-local
```

A successful reset explicitly reports that the vault was replaced with an empty
encrypted document and that `inventories/<slug>/.vault-pass` was regenerated.

Destroying a vault deletes only the selected provider's encrypted `vault.yml`
and `.vault-pass`. It leaves the provider inventory in place. The
provider-specific confirmation is required:

```sh
task vault-destroy PROVIDER=local CONFIRM=destroy-vault-local
```
