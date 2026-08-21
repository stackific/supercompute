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
creates each missing host from `provider.image.source` (`template:ubuntu-26.04`)
with `provider.resources` pinned to 1 CPU, 2 GiB RAM, and 5 GiB disk, and with
`--containerd=none --mount-none` so first boot does not wait on Lima's bundled
nerdctl install or home mounts. Existing instances are only started; their CPU,
memory, disk, containerd, and mounts are not rewritten.

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
