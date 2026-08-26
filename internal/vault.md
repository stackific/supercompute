# Ansible Vault

Each provider inventory has an encrypted vault and a local password file.

| Path | Purpose |
| --- | --- |
| `inventories/<provider>/group_vars/all/vault.yml` | Encrypted YAML |
| `inventories/<provider>/.vault-pass` | Vault password (operator-local) |

Vault ID label: `<project>-<provider>` (from `config.yml` + inventory slug). Header must match for `ansible-vault` operations.

## Document shape

Decrypted vault must contain:

```yaml
vault_meta:
  project: example   # must match config.yml
  provider: dev         # must match inventory slug
  secrets: { … }
```

`scripts/vault.py` validates this on edit. Legacy `deployment_vault` / `vault_prod_wireguard_*` keys are auto-migrated on `ensure-wireguard`, `migrate`, and before each playbook run.

## Tasks

| Task | Action |
| --- | --- |
| `task vault-init PROVIDER=<slug>` | Create empty encrypted vault + new password file |
| `task vault-edit PROVIDER=<slug>` | Decrypt, edit in `$EDITOR`, re-encrypt, validate |
| `task vault-wireguard-ensure PROVIDER=<slug>` | Ensure WireGuard key pairs exist in vault |
| `PROVIDER=<slug> uv run --locked python scripts/vault.py migrate` | Upgrade legacy vault key names in place |
| `task vault-destroy PROVIDER=<slug> CONFIRM=destroy-vault-<slug>` | Delete vault and password file |

To wipe and recreate a provider vault: `vault-destroy`, then `vault-init`.

`up` calls `vault.py ensure-wireguard` automatically before the WireGuard playbook.

## Dev reset

`task dev-reset CONFIRM=reset-dev` deletes the dev encrypted vault and its local
password file. It does not create replacement Vault content, so initialize it
before the next `up`:

```sh
task vault-init PROVIDER=dev
```

## WireGuard keys

`ensure-wireguard` generates per-node WireGuard key material in the vault when missing (`vault_wireguard_private_keys` / `vault_wireguard_public_keys`). Keys sync to `.state/<provider>/wireguard/` during `up`.

## Rename / migration

If `project` changes:

1. Decrypt vault with old vault-id label.
2. Update `vault_meta.project` inside the document.
3. Change `config.yml`.
4. Re-encrypt with the new vault-id label.

Mismatch between `config.yml`, vault header, and inner `project` causes decrypt or validation failures.

## Related

- [wireguard.md](wireguard.md) — mesh bring-up
- [cluster.md](cluster.md) — cluster runtime
