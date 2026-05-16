"""
P1-SEC-2: Sensitive Data Encryption

Provides Fernet symmetric encryption for API keys and other sensitive
configuration values stored in SQLite.

Usage:
    from app.core.security import encrypt_api_key, decrypt_api_key

    # Encrypt before storing
    encrypted = encrypt_api_key("sk-abc123...")

    # Decrypt when retrieving
    original = decrypt_api_key(encrypted)
"""

from __future__ import annotations

import base64
import logging
import os
import re
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# Fernet key MUST be 32 url-safe base64-encoded bytes.
# We derive it from ENCRYPTION_KEY env var, or generate+store on first run.
_KEY_ENV = "RABAIAGENT_ENCRYPTION_KEY"
_KEY_FILE = ".encryption.key"


@lru_cache()
def _get_fernet() -> Fernet:
    """Get or create the Fernet instance (singleton)."""
    key = os.environ.get(_KEY_ENV)

    if key:
        # Validate and pad if needed (support raw 32-byte hex as fallback)
        try:
            decoded = base64.urlsafe_b64decode(key)
            if len(decoded) == 32:
                key = base64.urlsafe_b64encode(decoded).decode()
            fernet = Fernet(key.encode())
            return fernet
        except Exception:
            pass

    # Generate a fresh key and warn the user
    raw_key = Fernet.generate_key()
    logger.warning(
        f"No {_KEY_ENV} set — generated a temporary key. "
        f"Set it in production: export {_KEY_ENV}={raw_key.decode()} "
        "(store this value securely, e.g. in your password manager)"
    )
    return Fernet(raw_key)


def encrypt_api_key(plaintext: str) -> str:
    """
    Encrypt a plaintext string (e.g. API key) for SQLite storage.

    Returns a base64-encoded string prefixed with "ENC:" so it's
    identifiable as encrypted in the DB.

    Usage:
        encrypted = encrypt_api_key("sk-live-xxxx")
        Settings.set("llm.openai.api_key", encrypted, category="llm")
    """
    if not plaintext:
        return plaintext

    # Don't double-encrypt
    if plaintext.startswith("ENC:"):
        return plaintext

    fernet = _get_fernet()
    encrypted = fernet.encrypt(plaintext.encode("utf-8"))
    return f"ENC:{encrypted.decode()}"


def decrypt_api_key(ciphertext: str) -> str:
    """
    Decrypt a ciphertext produced by encrypt_api_key().

    Returns the original plaintext. Returns the input unchanged if it
    doesn't start with "ENC:" (handles legacy unencrypted values).

    Usage:
        raw_key = decrypt_api_key(Settings.get("llm.openai.api_key"))
    """
    if not ciphertext:
        return ciphertext

    if not ciphertext.startswith("ENC:"):
        # Legacy unencrypted value — return as-is
        return ciphertext

    try:
        fernet = _get_fernet()
        encrypted = ciphertext[4:]  # Strip "ENC:" prefix
        decrypted = fernet.decrypt(encrypted.encode("utf-8"))
        return decrypted.decode("utf-8")
    except Exception as e:
        logger.error(f"Decryption failed (key mismatch?): {e}")
        raise ValueError("Failed to decrypt — check ENCRYPTION_KEY env var") from e


class FernetEncryption:
    """
    Class-based wrapper for Fernet encryption, useful for dependency injection.

    Example:
        class ApiKeyStore:
            def __init__(self, enc: FernetEncryption):
                self._enc = enc

            def store(self, key: str, value: str):
                Settings.set(key, self._enc.encrypt(value), category="api_keys")

            def retrieve(self, key: str) -> str:
                return self._enc.decrypt(Settings.get(key))
    """

    def encrypt(self, plaintext: str) -> str:
        return encrypt_api_key(plaintext)

    def decrypt(self, ciphertext: str) -> str:
        return decrypt_api_key(ciphertext)

    def re_encrypt(self, ciphertext: str) -> str:
        """
        Re-encrypt with the current key. Useful when rotating keys:
        read with old key → decrypt → re-encrypt with new key.
        """
        plaintext = self.decrypt(ciphertext)
        return self.encrypt(plaintext)


# ── Auto-upgrade Settings.set() to encrypt sensitive keys ───────────────────

SENSITIVE_KEY_PATTERNS = [
    re.compile(r".*api[_-]?key.*", re.IGNORECASE),
    re.compile(r".*secret.*", re.IGNORECASE),
    re.compile(r".*password.*", re.IGNORECASE),
    re.compile(r".*token.*", re.IGNORECASE),
    re.compile(r".*private[_-]?key.*", re.IGNORECASE),
]


def should_encrypt(key: str) -> bool:
    """Check if a Settings key should be encrypted before storage."""
    return any(p.match(key) for p in SENSITIVE_KEY_PATTERNS)


def encrypt_value_if_needed(key: str, value: object) -> object:
    """Auto-encrypt string values for sensitive keys."""
    if isinstance(value, str) and should_encrypt(key):
        return encrypt_api_key(value)
    return value


def decrypt_value_if_needed(key: str, value: object) -> object:
    """Auto-decrypt string values for sensitive keys."""
    if isinstance(value, str) and should_encrypt(key):
        try:
            return decrypt_api_key(value)
        except Exception:
            return value  # Return as-is if not encrypted
    return value
