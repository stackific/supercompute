# Ansible Vault

Each provider inventory has an encrypted vault and a local password file.

| Path | Purpose |
| --- | --- |
| `inventories/<provider>/group_vars/all/vault.yml` | Encrypted YAML |
| `inventories/<provider>/.vault-pass` | Vault password (operator-local) |

Vault ID label: `<deployment_name>-<provider>` (from `deployment.yml` + inventory slug). Header must match for `ansible-vault` operations.

## Document shape

Decrypted vault must contain:

```yaml
deployment_vault:
  deployment_name: sc   # must match deployment.yml
  provider: dev         # must match inventory slug
  secrets: { … }
```

`scripts/vault.py` validates this on edit.

## Tasks

| Task | Action |
| --- | --- |
| `task vault-init PROVIDER=<slug>` | Create empty encrypted vault + new password file |
| `task vault-edit PROVIDER=<slug>` | Decrypt, edit in `$EDITOR`, re-encrypt, validate |
| `task vault-wireguard-ensure PROVIDER=<slug>` | Ensure WireGuard key pairs exist in vault |
| `task vault-reset PROVIDER=<slug> CONFIRM=reset-vault-<slug>` | Empty vault + rotate password |
| `task vault-destroy PROVIDER=<slug> CONFIRM=destroy-vault-<slug>` | Delete vault and password file |

`up` calls `vault.py ensure-wireguard` automatically before the WireGuard playbook.

## Secrets used by cluster stack

When running `up`, vault may optionally provide (via `deployment_vault.secrets`):

| Key | Used for |
| --- | --- |
| `maxmind_account_id` | geoipupdate (optional; both keys required to enable GeoIP GeoDNS) |
| `maxmind_license_key` | geoipupdate (optional; both keys required to enable GeoIP GeoDNS) |

If either MaxMind key is missing, `up` still installs PowerDNS with a static authoritative zone (apex A → static hub mesh IP). Continent-based roaming GeoDNS is skipped.

## WireGuard keys

`ensure-wireguard` generates per-node WireGuard key material in the vault when missing. Keys sync to `.state/<provider>/wireguard/` during `up`.

## Rename / migration

If `deployment_name` changes:

1. Decrypt vault with old vault-id label.
2. Update `deployment_vault.deployment_name` inside the document.
3. Change `deployment.yml`.
4. Re-encrypt with the new vault-id label.

Mismatch between `deployment.yml`, vault header, and inner `deployment_name` causes decrypt or validation failures.

## Related

- [wireguard.md](wireguard.md) — mesh bring-up
- [cluster.md](cluster.md) — MaxMind secrets
