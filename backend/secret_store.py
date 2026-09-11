"""Small, dependency-light helpers for encrypted application secrets.

Callers supply the key material so this module can be shared by Flask
blueprints without importing ``app`` (which would create a circular import).
The format intentionally matches the Fernet values already used for MFA and
workspace WhatsApp credentials.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def _cipher(key_material: str) -> Fernet:
    key = base64.urlsafe_b64encode(
        hashlib.sha256(str(key_material).encode("utf-8")).digest()
    )
    return Fernet(key)


def encrypt_secret(value: str, key_material: str) -> str:
    if not key_material:
        raise RuntimeError("DATA_ENCRYPTION_KEY is required to encrypt credentials")
    return _cipher(key_material).encrypt(str(value).encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str, key_material: str, previous_key: str = "") -> str:
    if not value:
        return ""
    keys = [key_material]
    if previous_key and previous_key != key_material:
        keys.append(previous_key)
    for key in keys:
        if not key:
            continue
        try:
            return _cipher(key).decrypt(str(value).encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError, TypeError):
            continue
    return ""
