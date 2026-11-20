"""
Encryption of the sensitive text stored in the database (AES-256-GCM).

A stored value looks like `enc:v1:<key id>:<base64 of nonce + ciphertext>`. The key id
(first 8 hex digits of the key's SHA-256) tells which key encrypted it, so keys can be
changed: the old key stays in ENCRYPTION_OLD_KEYS until everything is re-encrypted.
Each value is bound to its column (associated data), so a ciphertext copied into
another column doesn't decrypt.
"""

import base64
import binascii
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PREFIX = "enc:v1:"
NONCE_SIZE = 12


class CryptoError(Exception):
    """A key is missing or wrong, or a stored value was changed."""


def generate_key() -> str:
    """A new random 256-bit key, base64-encoded for the .env file."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def parse_key(text: str) -> bytes:
    try:
        key = base64.urlsafe_b64decode(text.strip().encode())
    except (binascii.Error, ValueError):
        raise ValueError("an encryption key must be base64 (use python -m ticketbot "
                         "keygen)") from None
    if len(key) != 32:
        raise ValueError("an encryption key must be 32 bytes (use python -m ticketbot "
                         "keygen)")
    return key


def key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:8]


class Keyring:
    def __init__(self, current: bytes, old: list[bytes] | tuple = ()):
        self.current_id = key_id(current)
        self._keys = {key_id(k): AESGCM(k) for k in (*old, current)}

    def encrypt(self, text: str, context: str) -> str:
        nonce = os.urandom(NONCE_SIZE)
        sealed = self._keys[self.current_id].encrypt(nonce, text.encode(), context.encode())
        blob = base64.b64encode(nonce + sealed).decode()
        return f"{PREFIX}{self.current_id}:{blob}"

    def decrypt(self, value: str, context: str) -> str:
        if not is_encrypted(value):
            return value               # written before encryption, re-encrypted at startup
        kid, _, blob = value[len(PREFIX):].partition(":")
        aead = self._keys.get(kid)
        if aead is None:
            raise CryptoError(f"no key with id {kid}: add the old key to "
                              "ENCRYPTION_OLD_KEYS")
        try:
            raw = base64.b64decode(blob)
            return aead.decrypt(raw[:NONCE_SIZE], raw[NONCE_SIZE:], context.encode()).decode()
        except (InvalidTag, binascii.Error, ValueError):
            raise CryptoError(f"a value in {context} can't be decrypted: it was changed or "
                              "encrypted with another key") from None


def is_encrypted(value: str) -> bool:
    return value.startswith(PREFIX)


_active: Keyring | None = None


def configure(keyring: Keyring | None) -> None:
    """Set the keyring used by the database (once, at startup)."""
    global _active
    _active = keyring


def active() -> Keyring:
    if _active is None:
        raise CryptoError("ENCRYPTION_KEY is not configured")
    return _active
