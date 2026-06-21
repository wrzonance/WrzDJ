"""Tests for app.core.config.Settings derived properties."""

import base64
import secrets

import pytest
from cryptography.fernet import Fernet

from app.core.config import (
    Settings,
    _fernet_key_error,
    _fernet_key_list_error,
    validate_settings,
)


def _make_settings(**overrides) -> Settings:
    """Build a Settings instance bypassing env, with safe required defaults."""
    defaults = {
        "database_url": "sqlite:///:memory:",
        "jwt_secret": "test-secret-not-default",
        "env": "development",
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestEffectiveHumanCookieSecret:
    """Regression: secrets.token_urlsafe(32) yields 43-char unpadded base64.

    Production was set with such a value and base64.urlsafe_b64decode without
    padding raised binascii.Error, returning 500 from /verify-human.
    """

    def test_unpadded_43char_token_urlsafe(self) -> None:
        raw = secrets.token_bytes(32)
        unpadded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        assert len(unpadded) == 43

        s = _make_settings(human_cookie_secret=unpadded)
        assert s.effective_human_cookie_secret == raw

    def test_padded_44char_openssl_rand(self) -> None:
        raw = secrets.token_bytes(32)
        padded = base64.urlsafe_b64encode(raw).decode()
        assert padded.endswith("=")
        assert len(padded) == 44

        s = _make_settings(human_cookie_secret=padded)
        assert s.effective_human_cookie_secret == raw

    def test_invalid_base64_raises(self) -> None:
        s = _make_settings(human_cookie_secret="!!!not-base64!!!")
        with pytest.raises(Exception):  # noqa: B017,PT011
            _ = s.effective_human_cookie_secret

    def test_dev_autogenerates_when_unset(self) -> None:
        s = _make_settings(env="development", human_cookie_secret="")
        key = s.effective_human_cookie_secret
        assert isinstance(key, bytes)
        assert len(key) == 32
        # Cached: subsequent calls return same key
        assert s.effective_human_cookie_secret == key

    def test_production_unset_raises(self) -> None:
        s = _make_settings(env="production", human_cookie_secret="")
        with pytest.raises(RuntimeError, match="HUMAN_COOKIE_SECRET"):
            _ = s.effective_human_cookie_secret


class TestFernetKeyError:
    """Shape-validate TOKEN_ENCRYPTION_KEY so a malformed key fails loud at
    startup instead of crashing at the first OAuth token encryption (#504).
    """

    def test_valid_fernet_key_returns_none(self) -> None:
        assert _fernet_key_error(Fernet.generate_key().decode()) is None

    def test_hex_key_returns_error(self) -> None:
        # `openssl rand -hex 32` → 64 hex chars: not a valid Fernet key.
        hex_key = secrets.token_hex(32)
        assert len(hex_key) == 64
        err = _fernet_key_error(hex_key)
        assert err is not None
        assert "Fernet" in err

    def test_empty_returns_none(self) -> None:
        # Presence is checked separately; shape check ignores empty input.
        assert _fernet_key_error("") is None


class TestFernetKeyListError:
    """Validate the comma-separated rotation list (TOKEN_ENCRYPTION_KEYS) the
    same way app.core.encryption parses it: strip whitespace, drop empties,
    every remaining entry must be a valid Fernet key.
    """

    def test_all_valid_returns_none(self) -> None:
        keys = f"{Fernet.generate_key().decode()}, {Fernet.generate_key().decode()}"
        assert _fernet_key_list_error(keys, "TOKEN_ENCRYPTION_KEYS") is None

    def test_blank_only_returns_no_valid_keys(self) -> None:
        err = _fernet_key_list_error(" , ", "TOKEN_ENCRYPTION_KEYS")
        assert err is not None
        assert "no valid keys" in err

    def test_one_bad_entry_names_the_setting_and_index(self) -> None:
        keys = f"{Fernet.generate_key().decode()},{secrets.token_hex(32)}"
        err = _fernet_key_list_error(keys, "TOKEN_ENCRYPTION_KEYS")
        assert err is not None
        assert "TOKEN_ENCRYPTION_KEYS entry 2" in err


class TestValidateSettingsFernetShape:
    """validate_settings() must reject a malformed Fernet key in production for
    either the single TOKEN_ENCRYPTION_KEY or the rotation TOKEN_ENCRYPTION_KEYS,
    mirroring the precedence app.core.encryption uses at runtime.
    """

    def _prod_settings(self, *, token_key: str = "", token_keys: str = "") -> Settings:
        return _make_settings(
            env="production",
            jwt_secret="prod-secret-not-default",
            cors_origins="https://app.example.com",
            human_cookie_secret=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
            token_encryption_key=token_key,
            token_encryption_keys=token_keys,
        )

    def test_hex_token_key_exits(self, caplog) -> None:
        s = self._prod_settings(token_key=secrets.token_hex(32))
        with pytest.raises(SystemExit) as excinfo:
            validate_settings(s)
        assert excinfo.value.code == 1
        assert "TOKEN_ENCRYPTION_KEY is not a valid Fernet key" in caplog.text

    def test_valid_fernet_token_key_passes(self) -> None:
        s = self._prod_settings(token_key=Fernet.generate_key().decode())
        # Should not raise SystemExit.
        validate_settings(s)

    def test_rotation_only_valid_passes(self) -> None:
        # token_encryption_keys set, token_encryption_key empty — a valid
        # rotation-only config must NOT be rejected as "missing".
        s = self._prod_settings(token_keys=Fernet.generate_key().decode())
        validate_settings(s)

    def test_rotation_with_bad_entry_exits(self, caplog) -> None:
        keys = f"{Fernet.generate_key().decode()},{secrets.token_hex(32)}"
        s = self._prod_settings(token_keys=keys)
        with pytest.raises(SystemExit) as excinfo:
            validate_settings(s)
        assert excinfo.value.code == 1
        assert "TOKEN_ENCRYPTION_KEYS entry 2" in caplog.text

    def test_neither_key_set_exits(self, caplog) -> None:
        s = self._prod_settings()
        with pytest.raises(SystemExit):
            validate_settings(s)
        assert "TOKEN_ENCRYPTION_KEY" in caplog.text
