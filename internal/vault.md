# Ansible Vault

Each provider inventory has an encrypted vault and a local password file.

| Path | Purpose |
| --- | --- |
| `inventories/<provider>/group_vars/all/vault.yml` | Encrypted YAML (committed) |
| `inventories/<provider>/.vault-pass` | Vault password (operator-local / CI secret; **never** commit) |

Vault ID label: `<project>-<provider>` (from `hosts.yml` all.vars + inventory slug). Header must match for `ansible-vault` operations.

## `.vault-pass`

```sh
task vault-init ENV=<env>
```

That writes `inventories/<slug>/.vault-pass` (mode `0600`) and the encrypted vault.

Store a backup of `.vault-pass` off-repo (password manager). For GHA-managed providers, set repository secret `ANSIBLE_VAULT_PASSWORD` to the **exact** file contents (single line, no extra spaces).

## Document shape

After `vault-init`, decrypted vault contains:

```yaml
vault_meta:
  project: example   # must match hosts.yml all.vars
  provider: dev      # must match inventory slug
vault_database_url: postgresql://REPLACE_WITH_USER:PASSWORD@HOST:5432/DATABASE
vault_database_secret: …   # auto-generated at vault-init
```

After the first `task up`, the vault also has `vault_wireguard_private_keys` and `vault_wireguard_public_keys`.

Replace `vault_database_url` with `task vault-edit` before `task up` (see public docs — PostgreSQL database). `scripts/vault.py` validates the vault on edit.

## Tasks

| Task | Action |
| --- | --- |
| `task vault-init ENV=<env>` | Create empty encrypted vault + new password file |
| `task vault-edit ENV=<env>` | Open vault, edit secrets, save and exit |
| `task vault-secrets-ensure ENV=<env>` | Internal — ensure WireGuard keys and `vault_database_secret` (`up` calls this) |
| `task vault-wireguard-ensure ENV=<env>` | Internal — ensure WireGuard key pairs only |
| `task vault-destroy ENV=<env> CONFIRM=destroy-vault-<slug>` | Internal — delete vault without full reset |

To wipe and recreate a provider vault: `env-reset` (or `dev-reset` / `dev-reset-lima`), then `vault-init`.

`up` calls `vault.py ensure-secrets` automatically before playbooks. `scripts/validate-deployment.py` then checks `hosts.yml` (`project`, `hostname`) and vault secrets (`vault_database_url`, `vault_database_secret`).

## Environment reset

`task dev-reset CONFIRM=reset-dev` deletes the **dev** encrypted vault and its local
password file. `task dev-reset-lima CONFIRM=reset-dev-lima` does the same for **dev-lima**.

Neither creates replacement Vault content, so initialize before the next `up`:

```sh
task vault-init ENV=dev
# or
task vault-init ENV=dev-lima
```

## WireGuard keys

`ensure-wireguard` generates per-node WireGuard key material in the vault when missing (`vault_wireguard_private_keys` / `vault_wireguard_public_keys`). Keys sync to `.state/<provider>/wireguard/` during `up`. The `macos` key is still generated for Mac-managed inventories; GHA control planes omit the Mac peer from node configs.

## Database URL and secret

`vault-init` seeds `vault_database_url` as `postgresql://REPLACE_WITH_USER:PASSWORD@HOST:5432/DATABASE` and generates `vault_database_secret`. Replace the URL with `task vault-edit` before `task up`. `ensure-database-secret` (also run via `ensure-secrets`) adds the secret when missing. Ansible loads both from the encrypted vault like other `vault_*` variables.

## Rename project

If `project` changes:

1. Decrypt vault with old vault-id label.
2. Update `vault_meta.project` inside the document.
3. Change `hosts.yml` all.vars (`project`).
4. Re-encrypt with the new vault-id label.

Mismatch between `hosts.yml` all.vars, vault header, and inner `project` causes decrypt or validation failures.

## Related

- [wireguard.md](wireguard.md) — mesh bring-up
- [cluster.md](cluster.md) — cluster runtime
- [gha-deploy.md](gha-deploy.md) — GitHub Actions control plane
