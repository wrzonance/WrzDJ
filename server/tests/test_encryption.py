"""Tests for the encryption module (Fernet encrypt/decrypt + TypeDecorator)."""

from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import Column, Integer, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.encryption import (
    _FERNET_PREFIX,
    DecryptionError,
    EncryptedText,
    decrypt_value,
    encrypt_value,
    reset_fernet,
)

# Use a stable test key so encrypt/decrypt are deterministic across calls.
TEST_KEY = Fernet.generate_key().decode()

Base = declarative_base()


class FakeSecret(Base):
    __tablename__ = "fake_secrets"
    id = Column(Integer, primary_key=True)
    token = Column(EncryptedText, nullable=True)


@pytest.fixture(autouse=True)
def _use_test_key():
    """Ensure every test uses a known Fernet key and resets state afterwards."""
    reset_fernet()
    with patch("app.core.encryption._get_fernet", return_value=Fernet(TEST_KEY)):
        yield
    reset_fernet()


class TestEncryptDecrypt:
    def test_round_trip(self):
        plaintext = "my-secret-token-12345"
        encrypted = encrypt_value(plaintext)
        assert encrypted is not None
        assert encrypted != plaintext
        assert encrypted.startswith(_FERNET_PREFIX)
        assert decrypt_value(encrypted) == plaintext

    def test_none_passthrough(self):
        assert encrypt_value(None) is None
        assert decrypt_value(None) is None

    def test_plaintext_fallback_allowed_when_flag_true(self):
        """Legacy plaintext is returned as-is when ALLOW_LEGACY_PLAINTEXT_TOKENS=True."""
        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.allow_legacy_plaintext_tokens = True
            legacy = "some-old-plaintext-token"
            assert decrypt_value(legacy) == legacy

    def test_plaintext_fallback_raises_when_flag_false(self):
        """H-C3: legacy plaintext raises DecryptionError when flag is False."""
        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.allow_legacy_plaintext_tokens = False
            with pytest.raises(DecryptionError, match="ALLOW_LEGACY_PLAINTEXT_TOKENS"):
                decrypt_value("some-old-plaintext-token")

    def test_invalid_token_raises_decryption_error(self):
        """H-C2: Fernet InvalidToken must raise DecryptionError, not return ciphertext."""
        # Create a valid-looking Fernet ciphertext with a DIFFERENT key
        other_key = Fernet.generate_key()
        other_fernet = Fernet(other_key)
        wrong_ciphertext = other_fernet.encrypt(b"secret").decode()
        assert wrong_ciphertext.startswith(_FERNET_PREFIX)

        with pytest.raises(DecryptionError, match="wrong key"):
            decrypt_value(wrong_ciphertext)

    def test_empty_string(self):
        encrypted = encrypt_value("")
        assert encrypted is not None
        assert decrypt_value(encrypted) == ""

    def test_unicode_round_trip(self):
        text = "token-with-unicode-\u00e9\u00e8\u00ea"
        assert decrypt_value(encrypt_value(text)) == text


class TestMultiFernetRotation:
    """H-C1 guard: MultiFernet supports key rotation without data migration.

    Rotation model:
    - TOKEN_ENCRYPTION_KEYS="new,old" during rotation window
    - First key in list encrypts new data
    - All keys tried in order for decryption
    - Ciphertext from old key still decrypts; re-encrypting under new key
      is an explicit backfill step, not automatic

    These tests install their own _get_fernet override (inner patch) to
    supersede the outer autouse fixture, returning a MultiFernet with the
    configured key list.
    """

    def test_single_key_via_new_plural_field(self):
        """MultiFernet with one key behaves like old single-key setup."""
        key = Fernet.generate_key()
        mf = MultiFernet([Fernet(key)])
        with patch("app.core.encryption._get_fernet", return_value=mf):
            ct = encrypt_value("hello")
            assert decrypt_value(ct) == "hello"

    def test_rotation_old_ciphertext_decrypts_after_rotation(self):
        """Ciphertext encrypted under key A still decrypts when keys=[B, A]."""
        key_a = Fernet.generate_key()
        key_b = Fernet.generate_key()

        # Encrypt under key A only
        mf_a = MultiFernet([Fernet(key_a)])
        with patch("app.core.encryption._get_fernet", return_value=mf_a):
            ciphertext_a = encrypt_value("secret-payload")
            assert ciphertext_a is not None

        # Rotate: [B, A] — B encrypts new, A still decrypts old
        mf_rotated = MultiFernet([Fernet(key_b), Fernet(key_a)])
        with patch("app.core.encryption._get_fernet", return_value=mf_rotated):
            assert decrypt_value(ciphertext_a) == "secret-payload"
            new_ct = encrypt_value("new-payload")
            assert new_ct != ciphertext_a
            assert decrypt_value(new_ct) == "new-payload"

    def test_old_ciphertext_fails_after_key_removed(self):
        """Removing the old key from rotation makes old ciphertext undecryptable."""
        key_a = Fernet.generate_key()
        key_b = Fernet.generate_key()

        mf_a = MultiFernet([Fernet(key_a)])
        with patch("app.core.encryption._get_fernet", return_value=mf_a):
            ciphertext_a = encrypt_value("secret-payload")

        # Key A removed — only B remains
        mf_b = MultiFernet([Fernet(key_b)])
        with patch("app.core.encryption._get_fernet", return_value=mf_b):
            with pytest.raises(DecryptionError):
                decrypt_value(ciphertext_a)

    def test_rotate_method_reencrypts_under_first_key(self):
        """MultiFernet.rotate() re-encrypts ciphertext under the first key.
        This is what a backfill migration would use."""
        key_a = Fernet.generate_key()
        key_b = Fernet.generate_key()

        mf_a = MultiFernet([Fernet(key_a)])
        with patch("app.core.encryption._get_fernet", return_value=mf_a):
            old_ct = encrypt_value("payload")

        # Rotate: [B, A]
        mf_rotated = MultiFernet([Fernet(key_b), Fernet(key_a)])
        with patch("app.core.encryption._get_fernet", return_value=mf_rotated):
            # Re-encrypt under new primary key (backfill step)
            new_ct = mf_rotated.rotate(old_ct.encode()).decode()
            assert new_ct != old_ct
            # Both still decrypt to original plaintext
            assert decrypt_value(old_ct) == "payload"
            assert decrypt_value(new_ct) == "payload"

        # Key A removed — new_ct still works, old_ct does not
        mf_b = MultiFernet([Fernet(key_b)])
        with patch("app.core.encryption._get_fernet", return_value=mf_b):
            assert decrypt_value(new_ct) == "payload"
            with pytest.raises(DecryptionError):
                decrypt_value(old_ct)


class TestEncryptedTextTypeDecorator:
    @pytest.fixture
    def session(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        _session = sessionmaker(bind=engine)()
        yield _session
        try:
            _session.close()
        finally:
            engine.dispose()

    def test_write_and_read_encrypted(self, session: Session):
        secret = FakeSecret(id=1, token="super-secret")
        session.add(secret)
        session.commit()

        # Read back via ORM — should be decrypted transparently
        loaded = session.get(FakeSecret, 1)
        assert loaded is not None
        assert loaded.token == "super-secret"

    def test_raw_value_is_encrypted(self, session: Session):
        secret = FakeSecret(id=2, token="plaintext-value")
        session.add(secret)
        session.commit()
        session.expire_all()

        # Read raw from DB to confirm it's actually encrypted
        from sqlalchemy import text

        raw = session.execute(text("SELECT token FROM fake_secrets WHERE id = 2")).scalar()
        assert raw is not None
        assert raw.startswith(_FERNET_PREFIX)
        assert raw != "plaintext-value"

    def test_null_column(self, session: Session):
        secret = FakeSecret(id=3, token=None)
        session.add(secret)
        session.commit()

        loaded = session.get(FakeSecret, 3)
        assert loaded is not None
        assert loaded.token is None
