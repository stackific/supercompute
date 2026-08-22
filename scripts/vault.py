from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import sys
import tempfile

import yaml


ROOT = Path(__file__).resolve().parents[1]


class VaultError(RuntimeError):
  pass


def deployment_name() -> str:
  path = ROOT / "deployment.yml"
  try:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
  except FileNotFoundError as error:
    raise VaultError(f"Deployment configuration does not exist: {path}") from error
  except yaml.YAMLError as error:
    raise VaultError(f"Deployment configuration is not valid YAML: {error}") from error

  if not isinstance(document, dict):
    raise VaultError("deployment.yml must contain a YAML mapping")
  name = document.get("deployment_name")
  if not isinstance(name, str) or not name.strip():
    raise VaultError("deployment.yml must contain a non-empty deployment_name")
  if Path(name).name != name or name in {".", ".."}:
    raise VaultError("deployment_name must be a single path-safe name")
  return name


def provider_directories() -> dict[str, Path]:
  inventories = ROOT / "inventories"
  if not inventories.is_dir():
    raise VaultError(f"Inventory directory does not exist: {inventories}")

  return {
    path.name: path
    for path in sorted(inventories.iterdir())
    if path.is_dir() and (path / "hosts.yml").is_file()
  }


def provider_from_environment() -> str:
  provider = os.environ.get("PROVIDER", "")
  providers = provider_directories()
  if provider not in providers:
    choices = ", ".join(providers) if providers else "none"
    raise VaultError(
      "PROVIDER must match an inventories/<slug>/hosts.yml entry; "
      f"available providers: {choices}"
    )
  return provider


def inventory_directory(provider: str) -> Path:
  try:
    return provider_directories()[provider]
  except KeyError as error:
    raise VaultError(f"Provider inventory does not exist: {provider}") from error


def password_path(provider: str) -> Path:
  return inventory_directory(provider) / ".vault-pass"


def vault_path(provider: str) -> Path:
  return inventory_directory(provider) / "group_vars" / "all" / "vault.yml"


def run_ansible_vault(*arguments: str, capture_output: bool = False) -> str:
  result = subprocess.run(
    ["ansible-vault", *arguments],
    cwd=ROOT,
    check=False,
    text=True,
    stdout=subprocess.PIPE if capture_output else None,
    stderr=subprocess.PIPE if capture_output else None,
  )
  if result.returncode != 0:
    detail = result.stderr.strip() if result.stderr else "ansible-vault failed"
    raise VaultError(detail)
  return result.stdout if result.stdout else ""


def validate_document(content: str, provider: str) -> None:
  try:
    document = yaml.safe_load(content)
  except yaml.YAMLError as error:
    raise VaultError(f"Vault is not valid YAML: {error}") from error

  if not isinstance(document, dict):
    raise VaultError("Vault root must be a YAML mapping")

  vault = document.get("deployment_vault")
  if not isinstance(vault, dict):
    raise VaultError("Vault must contain a deployment_vault mapping")
  if vault.get("deployment_name") != deployment_name():
    raise VaultError(
      f"deployment_vault.deployment_name must be {deployment_name()}"
    )
  if vault.get("provider") != provider:
    raise VaultError(f"deployment_vault.provider must be {provider}")
  if not isinstance(vault.get("secrets"), dict):
    raise VaultError("deployment_vault.secrets must be a mapping")


def empty_document(provider: str) -> str:
  return yaml.safe_dump(
    {
      "deployment_vault": {
        "deployment_name": deployment_name(),
        "provider": provider,
        "secrets": {},
      }
    },
    explicit_start=True,
    sort_keys=False,
  )


def generate_password() -> str:
  return secrets.token_urlsafe(48)


def write_password(path: Path, password: str) -> None:
  descriptor, temporary_name = tempfile.mkstemp(
    dir=path.parent,
    prefix=f"{path.name}.tmp.",
  )
  temporary_path = Path(temporary_name)
  try:
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
      stream.write(f"{password}\n")
    temporary_path.replace(path)
    path.chmod(0o600)
  finally:
    temporary_path.unlink(missing_ok=True)


def read_password(path: Path) -> str:
  try:
    password = path.read_text(encoding="utf-8").rstrip("\r\n")
  except FileNotFoundError as error:
    raise VaultError(
      f"Run task vault-init to create {path.relative_to(ROOT)} first"
    ) from error
  if not password:
    raise VaultError(f"Vault password file is empty: {path}")
  path.chmod(0o600)
  return password


def temporary_password_file(password: str):
  directory = tempfile.TemporaryDirectory(
    prefix=f"{deployment_name()}-vault-password-"
  )
  path = Path(directory.name) / "password"
  path.write_text(f"{password}\n", encoding="utf-8")
  path.chmod(0o600)
  return directory, path


def vault_label(provider: str) -> str:
  return f"{deployment_name()}-{provider}"


def vault_id(provider: str, password_file: Path) -> str:
  return f"{vault_label(provider)}@{password_file}"


def decrypt(path: Path, provider: str, password_file: Path) -> str:
  if not path.is_file():
    raise VaultError(f"Vault does not exist: {path}")
  content = run_ansible_vault(
    "view",
    "--vault-id",
    vault_id(provider, password_file),
    str(path),
    capture_output=True,
  )
  validate_document(content, provider)
  return content


def encrypted_temporary_path(destination: Path) -> Path:
  destination.parent.mkdir(parents=True, exist_ok=True)
  descriptor, name = tempfile.mkstemp(
    dir=destination.parent,
    prefix=f".{destination.name}.",
  )
  os.close(descriptor)
  path = Path(name)
  path.unlink()
  return path


def encrypt_and_replace(
  plaintext: Path,
  destination: Path,
  provider: str,
  password_file: Path,
) -> None:
  encrypted = encrypted_temporary_path(destination)
  try:
    run_ansible_vault(
      "encrypt",
      "--vault-id",
      vault_id(provider, password_file),
      "--encrypt-vault-id",
      vault_label(provider),
      "--output",
      str(encrypted),
      str(plaintext),
      capture_output=True,
    )
    decrypt(encrypted, provider, password_file)
    encrypted.replace(destination)
  finally:
    encrypted.unlink(missing_ok=True)


def create_empty_vault(provider: str, password: str) -> None:
  destination = vault_path(provider)
  prefix = f"{deployment_name()}-vault-init-"
  with tempfile.TemporaryDirectory(prefix=prefix) as directory_name:
    directory = Path(directory_name)
    plaintext = directory / "vault.yml"
    plaintext.write_text(empty_document(provider), encoding="utf-8")
    plaintext.chmod(0o600)
    password_directory, temporary_password = temporary_password_file(password)
    try:
      encrypt_and_replace(
        plaintext,
        destination,
        provider,
        temporary_password,
      )
    finally:
      password_directory.cleanup()


def initialize(provider: str) -> None:
  password_file = password_path(provider)
  encrypted_vault = vault_path(provider)

  if encrypted_vault.is_file():
    if not password_file.is_file():
      raise VaultError(
        f"Restore {password_file.relative_to(ROOT)}; the encrypted vault already "
        "exists"
      )
    raise VaultError(
      f"Vault is already initialized: {encrypted_vault.relative_to(ROOT)}; "
      "use vault-edit, vault-reset, or vault-destroy"
    )

  if not password_file.is_file():
    write_password(password_file, generate_password())

  password = read_password(password_file)
  create_empty_vault(provider, password)
  print(f"Vault initialized: {encrypted_vault.relative_to(ROOT)}")


def edit(provider: str) -> None:
  password_file = password_path(provider)
  encrypted_vault = vault_path(provider)
  read_password(password_file)
  content = decrypt(encrypted_vault, provider, password_file)

  prefix = f"{deployment_name()}-vault-{provider}-"
  with tempfile.TemporaryDirectory(prefix=prefix) as name:
    plaintext = Path(name) / "vault.yml"
    plaintext.write_text(content, encoding="utf-8")
    plaintext.chmod(0o600)

    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    command = [*shlex.split(editor), str(plaintext)]
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
      raise VaultError(f"Editor exited with status {result.returncode}")

    edited_content = plaintext.read_text(encoding="utf-8")
    validate_document(edited_content, provider)
    encrypt_and_replace(
      plaintext,
      encrypted_vault,
      provider,
      password_file,
    )

  print(f"Vault validated and synced: {encrypted_vault.relative_to(ROOT)}")


def reset(provider: str) -> None:
  expected = f"reset-vault-{provider}"
  supplied = os.environ.get("CONFIRM", "")
  if supplied != expected:
    raise VaultError(f"CONFIRM must be exactly {expected}")

  password_file = password_path(provider)
  password = generate_password()
  create_empty_vault(provider, password)
  write_password(password_file, password)
  print(
    "Vault reset to an empty encrypted document: "
    f"{vault_path(provider).relative_to(ROOT)}"
  )
  print(f"Vault password regenerated: {password_file.relative_to(ROOT)}")


def destroy(provider: str) -> None:
  expected = f"destroy-vault-{provider}"
  supplied = os.environ.get("CONFIRM", "")
  if supplied != expected:
    raise VaultError(f"CONFIRM must be exactly {expected}")

  encrypted_vault = vault_path(provider)
  password_file = password_path(provider)

  try:
    encrypted_vault.unlink()
    print(f"Encrypted vault deleted: {encrypted_vault.relative_to(ROOT)}")
  except FileNotFoundError:
    print(f"Encrypted vault already absent: {encrypted_vault.relative_to(ROOT)}")

  try:
    password_file.unlink()
    print(f"Vault password deleted: {password_file.relative_to(ROOT)}")
  except FileNotFoundError:
    print(f"Vault password already absent: {password_file.relative_to(ROOT)}")


def deployment_host_names(provider: str) -> list[str]:
  path = inventory_directory(provider) / "hosts.yml"
  try:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
  except FileNotFoundError as error:
    raise VaultError(f"Provider inventory does not exist: {path}") from error
  except yaml.YAMLError as error:
    raise VaultError(f"Invalid YAML in {path}: {error}") from error

  if not isinstance(document, dict):
    raise VaultError("hosts.yml must contain a YAML mapping")
  children = document.get("all")
  if not isinstance(children, dict):
    raise VaultError("hosts.yml must contain an all mapping")
  groups = children.get("children")
  if not isinstance(groups, dict):
    raise VaultError("hosts.yml must contain all.children")
  deployment = groups.get("deployment")
  if not isinstance(deployment, dict):
    raise VaultError("hosts.yml must contain all.children.deployment")
  hosts = deployment.get("hosts")
  if hosts is None:
    return []
  if not isinstance(hosts, dict):
    raise VaultError("deployment.hosts must be a mapping")
  return sorted(hosts)


def generate_wireguard_keypair() -> tuple[str, str]:
  private = subprocess.run(
    ["wg", "genkey"],
    check=False,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
  )
  if private.returncode != 0:
    detail = private.stderr.strip() if private.stderr else "wg genkey failed"
    raise VaultError(detail)
  private_key = private.stdout.strip()
  public = subprocess.run(
    ["wg", "pubkey"],
    input=private_key,
    check=False,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
  )
  if public.returncode != 0:
    detail = public.stderr.strip() if public.stderr else "wg pubkey failed"
    raise VaultError(detail)
  return private_key, public.stdout.strip()


def ensure_wireguard(provider: str) -> None:
  platform_path = (
    inventory_directory(provider) / "group_vars" / "all" / "main.yml"
  )
  try:
    platform_document = yaml.safe_load(platform_path.read_text(encoding="utf-8"))
  except FileNotFoundError as error:
    raise VaultError(f"Provider configuration does not exist: {platform_path}") from error
  except yaml.YAMLError as error:
    raise VaultError(f"Invalid YAML in {platform_path}: {error}") from error
  if not isinstance(platform_document, dict):
    raise VaultError(f"{platform_path} must contain a YAML mapping")
  provider_config = platform_document.get("provider")
  if not isinstance(provider_config, dict):
    raise VaultError(f"{platform_path} must contain a provider mapping")
  platform = provider_config.get("platform")
  if platform == "public":
    private_key_field = "vault_prod_wireguard_private_keys"
    public_key_field = "vault_prod_wireguard_public_keys"
  elif platform in {"lima", "vps"}:
    raise VaultError(
      f"provider.platform={platform} is refused; use provider.platform=public "
      f"(WireGuard key ensure for {provider})"
    )
  else:
    raise VaultError(
      f"WireGuard key ensure supports public providers; refused for {provider} "
      f"(provider.platform={platform})"
    )

  if subprocess.run(["which", "wg"], check=False, capture_output=True).returncode != 0:
    raise VaultError("Install wireguard-tools (wg) before ensuring WireGuard vault keys")

  password_file = password_path(provider)
  encrypted_vault = vault_path(provider)
  read_password(password_file)
  content = decrypt(encrypted_vault, provider, password_file)
  document = yaml.safe_load(content)
  if not isinstance(document, dict):
    raise VaultError("Vault root must be a YAML mapping")

  required_names = ["macos", *deployment_host_names(provider)]
  private_keys = document.get(private_key_field)
  public_keys = document.get(public_key_field)
  if private_keys is None:
    private_keys = {}
  if public_keys is None:
    public_keys = {}
  if not isinstance(private_keys, dict) or not isinstance(public_keys, dict):
    raise VaultError(f"{private_key_field} and {public_key_field} must be mappings")

  changed = False
  for name in required_names:
    private = private_keys.get(name)
    public = public_keys.get(name)
    if isinstance(private, str) and private and isinstance(public, str) and public:
      continue
    if (isinstance(private, str) and private) ^ (isinstance(public, str) and public):
      raise VaultError(
        f"WireGuard key pair for {name} is incomplete; fix with vault-edit"
      )
    generated_private, generated_public = generate_wireguard_keypair()
    private_keys[name] = generated_private
    public_keys[name] = generated_public
    changed = True

  if not changed:
    print(f"WireGuard vault keys already present for {provider}")
    return

  document[private_key_field] = private_keys
  document[public_key_field] = public_keys
  plaintext_body = yaml.safe_dump(document, explicit_start=True, sort_keys=False)

  prefix = f"{deployment_name()}-vault-wg-{provider}-"
  with tempfile.TemporaryDirectory(prefix=prefix) as name:
    plaintext = Path(name) / "vault.yml"
    plaintext.write_text(plaintext_body, encoding="utf-8")
    plaintext.chmod(0o600)
    encrypt_and_replace(
      plaintext,
      encrypted_vault,
      provider,
      password_file,
    )

  print(f"WireGuard vault keys ensured: {encrypted_vault.relative_to(ROOT)}")


def parse_arguments() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Manage deployment provider vaults")
  parser.add_argument(
    "action",
    choices=("init", "edit", "reset", "destroy", "ensure-wireguard"),
  )
  return parser.parse_args()


def main() -> int:
  arguments = parse_arguments()
  try:
    provider = provider_from_environment()
    if arguments.action == "init":
      initialize(provider)
    elif arguments.action == "edit":
      edit(provider)
    elif arguments.action == "reset":
      reset(provider)
    elif arguments.action == "ensure-wireguard":
      ensure_wireguard(provider)
    else:
      destroy(provider)
  except VaultError as error:
    print(f"error: {error}", file=sys.stderr)
    return 1
  except KeyboardInterrupt:
    print("\nVault operation cancelled", file=sys.stderr)
    return 130
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
