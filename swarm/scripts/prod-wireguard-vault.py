#!/usr/bin/env python3
"""Generate and validate production WireGuard key maps without a local wg binary."""

from __future__ import annotations

import argparse
import base64
import binascii
import hmac
import re
import sys
from pathlib import Path

import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey


HOST_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
PRIVATE_FIELD = "vault_prod_wireguard_private_keys"
PUBLIC_FIELD = "vault_prod_wireguard_public_keys"


def parse_hosts(values: list[str]) -> list[str]:
    if not values or len(values) != len(set(values)) or any(not HOST_RE.fullmatch(value) for value in values):
        raise ValueError("WireGuard host names must be unique lower-case inventory aliases.")
    return values


def raw_private_key() -> tuple[str, str]:
    private = X25519PrivateKey.generate()
    private_raw = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return base64.b64encode(private_raw).decode("ascii"), base64.b64encode(public_raw).decode("ascii")


def emit(hosts: list[str]) -> None:
    pairs = {host: raw_private_key() for host in hosts}
    print(f"{PRIVATE_FIELD}:")
    for host, (private, _) in pairs.items():
        print(f"  {host}: '{private}'")
    print(f"{PUBLIC_FIELD}:")
    for host, (_, public) in pairs.items():
        print(f"  {host}: '{public}'")


def read_vault(path: Path) -> dict[str, object]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("The decrypted Vault must contain a YAML mapping.")
    return document


def state(document: dict[str, object], hosts: list[str]) -> str:
    private = document.get(PRIVATE_FIELD)
    public = document.get(PUBLIC_FIELD)
    if private is None and public is None:
        return "absent"
    if not isinstance(private, dict) or not isinstance(public, dict):
        return "partial"
    if any(host not in private or host not in public for host in hosts):
        return "partial"
    return "complete"


def decode_key(value: object, field: str, host: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{field}.{host} must be a base64 WireGuard key string.")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError(f"{field}.{host} is not valid base64.") from exc
    if len(decoded) != 32:
        raise ValueError(f"{field}.{host} must decode to exactly 32 bytes.")
    return decoded


def verify(document: dict[str, object], hosts: list[str]) -> None:
    if state(document, hosts) != "complete":
        raise ValueError("The production WireGuard Vault state is incomplete.")
    private_map = document[PRIVATE_FIELD]
    public_map = document[PUBLIC_FIELD]
    assert isinstance(private_map, dict) and isinstance(public_map, dict)
    for host in hosts:
        private = decode_key(private_map[host], PRIVATE_FIELD, host)
        configured_public = decode_key(public_map[host], PUBLIC_FIELD, host)
        derived_public = X25519PrivateKey.from_private_bytes(private).public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        if not hmac.compare_digest(derived_public, configured_public):
            raise ValueError(f"The production WireGuard keypair for {host} is inconsistent.")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("emit", "status", "verify"):
        child = subparsers.add_parser(name)
        child.add_argument("--hosts", nargs="+", required=True)
        if name != "emit":
            child.add_argument("--vault", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        hosts = parse_hosts(arguments.hosts)
        if arguments.command == "emit":
            emit(hosts)
            return 0
        document = read_vault(arguments.vault)
        if arguments.command == "status":
            print(state(document, hosts))
        else:
            verify(document, hosts)
            print("verified")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
