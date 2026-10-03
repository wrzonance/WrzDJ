"""Fernet encryption for OAuth tokens stored in the database.

Provides transparent encrypt-on-write / decrypt-on-read via a SQLAlchemy
TypeDecorator.  The encryption key(s) come from TOKEN_ENCRYPTION_KEYS
(comma-separated for rotation) or TOKEN_ENCRYPTION_KEY (single key, legacy).
In development, a key is auto-generated if none set.  In production, a
missing key is a fatal startup error (enforced in config.py).

SECURITY (H-C1): uses MultiFernet so key rotation is a config change, not
a data migration. The first key encrypts; all keys are tried for decrypt.
Rotation procedure: set TOKEN_ENCRYPTION_KEYS=<new>,<old>, deploy, run a
backfill that re-encrypts existing ciphertext under the new key, then
remove the old key from the env.
"""

import logging

import sqlalchemy as sa
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

logger = logging.getLogger(__name__)


class DecryptionError(Exception):
    """Raised when Fernet decryption fails (wrong key, corrupted ciphertext).

    SECURITY (H-C2): prior to this change, decrypt_value silently returned
    the raw ciphertext on failure, which could then be sent to upstream
    APIs (Beatport, Tidal) as a bearer token. Raising instead makes key
    rotation failures loud and prevents ciphertext leakage.
    """


# Module-level MultiFernet instance, lazily initialised on first use.
_fernet: MultiFernet | None = None

# Fernet ciphertexts always start with this prefix (base64 version byte).
_FERNET_PREFIX = "gAAAAA"


def _get_fernet() -> MultiFernet:
    """Return (or create) the module-level MultiFernet instance.

    Reads keys from settings.token_encryption_keys (comma-separated) with
    fallback to the legacy single settings.token_encryption_key. The first
    key encrypts new data; all keys are tried for decryption.
    """
    global _fernet  # noqa: PLW0603
    if _fernet is not None:
        return _fernet

    from app.core.config import get_settings

    settings = get_settings()
    keys_str = settings.token_encryption_keys or settings.token_encryption_key

    if not keys_str:
        # Dev/test fallback — generate an ephemeral key.
        keys_str = Fernet.generate_key().decode()
        logger.warning("TOKEN_ENCRYPTION_KEYS not set — using auto-generated ephemeral key")

    # Parse comma-separated keys (rotation support). Strip whitespace, drop empties.
    key_list = [k.strip() for k in keys_str.split(",") if k.strip()]
    if not key_list:
        raise ValueError("TOKEN_ENCRYPTION_KEYS contains no valid keys")

    fernets = [Fernet(k.encode() if isinstance(k, str) else k) for k in key_list]
    _fernet = MultiFernet(fernets)
    return _fernet


def encrypt_value(plaintext: str | None) -> str | None:
    """Encrypt a string value using Fernet.  Returns None for None input."""
    if plaintext is None:
        return None
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str | None) -> str | None:
    """Decrypt a Fernet-encrypted value.

    SECURITY (H-C2): raises DecryptionError on InvalidToken instead of
    silently returning ciphertext. This prevents botched key rotations
    from leaking Fernet ciphertext to upstream APIs.

    SECURITY (H-C3): the legacy plaintext passthrough is gated behind
    ALLOW_LEGACY_PLAINTEXT_TOKENS (default: True for backward compat
    during migration window). Set to False once all rows are encrypted.
    """
    if ciphertext is None:
        return None

    if not ciphertext.startswith(_FERNET_PREFIX):
        # Legacy plaintext — only allowed if feature flag is set
        from app.core.config import get_settings

        if get_settings().allow_legacy_plaintext_tokens:
            return ciphertext
        raise DecryptionError(
            "Value does not look like Fernet ciphertext and "
            "ALLOW_LEGACY_PLAINTEXT_TOKENS is disabled"
        )

    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError("Failed to decrypt value — wrong key or corrupted data") from exc


def decrypt_encrypted_value(ciphertext: str) -> str:
    """Decrypt a value only when it has the Fernet prefix; never allow legacy plaintext."""
    if not ciphertext.startswith(_FERNET_PREFIX):
        raise DecryptionError("Value is not Fernet-encrypted")
    plaintext = decrypt_value(ciphertext)
    if plaintext is None:
        raise DecryptionError("Encrypted value was empty")
    return plaintext


def reset_fernet() -> None:
    """Reset the cached Fernet instance (for testing only)."""
    global _fernet  # noqa: PLW0603
    _fernet = None


class EncryptedText(sa.types.TypeDecorator):
    """SQLAlchemy column type that transparently encrypts/decrypts via Fernet."""

    impl = sa.Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: sa.Dialect) -> str | None:
        """Encrypt before writing to the database."""
        return encrypt_value(value)

    def process_result_value(self, value: str | None, dialect: sa.Dialect) -> str | None:
        """Decrypt after reading from the database."""
        return decrypt_value(value)
