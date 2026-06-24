"""DEV_AUTH_BYPASS — a dev-only flag that skips the guest human-verification and
email-verification gates so headless tests can exercise guest flows without minting a
wrzdj_human cookie or verifying an email.

The critical contract under test: it is INERT in production (the property gates on
``not is_production``) AND ``validate_settings`` refuses to boot if it is ever set with
ENV=production — so it can never silently weaken a deployment.
"""

import base64
import logging
import secrets
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

import app.core.config as config
from app.core.config import Settings, validate_settings


class TestAuthBypassProperty:
    def test_active_in_dev_with_flag(self):
        assert Settings(env="development", dev_auth_bypass=True).auth_bypass_enabled is True

    def test_inert_in_production_even_with_flag(self):
        # Even if the flag leaks into a prod environment, the property is False.
        assert Settings(env="production", dev_auth_bypass=True).auth_bypass_enabled is False

    def test_off_by_default(self):
        assert Settings(env="development").auth_bypass_enabled is False


class TestProdSafety:
    def _prod_settings(self, **overrides) -> Settings:
        base = dict(
            env="production",
            jwt_secret="prod-secret-not-default",
            cors_origins="https://app.example.com",
            human_cookie_secret=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
            token_encryption_key=Fernet.generate_key().decode(),
        )
        base.update(overrides)
        return Settings(**base)

    def test_bypass_in_production_refuses_to_boot(self, caplog):
        s = self._prod_settings(dev_auth_bypass=True)
        with pytest.raises(SystemExit) as exc:
            validate_settings(s)
        assert exc.value.code == 1
        assert "DEV_AUTH_BYPASS must NOT be set in production" in caplog.text

    def test_clean_production_still_boots(self):
        # The same prod config WITHOUT the bypass must validate cleanly.
        validate_settings(self._prod_settings())

    def test_bypass_in_dev_warns_but_boots(self, caplog):
        with caplog.at_level(logging.WARNING):
            validate_settings(Settings(env="development", dev_auth_bypass=True))
        assert any("DEV_AUTH_BYPASS is ACTIVE" in r.message for r in caplog.records)


class TestGateBypassIntegration:
    """A gated guest endpoint (GET /collect/{code}/profile uses the hard
    require_verified_human) is blocked without a cookie, and passes when the bypass is on."""

    def test_gate_blocks_without_bypass(self, client, test_event):
        client.cookies.clear()
        r = client.get(f"/api/public/collect/{test_event.code}/profile")
        assert r.status_code == 403

    def test_bypass_lets_gated_endpoint_through(self, client, test_event):
        client.cookies.clear()
        bypass = Settings(env="development", dev_auth_bypass=True)
        with patch.object(config, "get_settings", lambda: bypass):
            r = client.get(f"/api/public/collect/{test_event.code}/profile")
        assert r.status_code == 200, r.text

    def test_bypass_covers_inline_guest_resolution(self, client, test_event, test_request):
        """The vote endpoint resolves the guest INLINE via get_guest_id (its own 401),
        not via the gate deps — so the bypass must cover that chokepoint too."""
        client.cookies.clear()
        # Without a guest cookie the inline resolver returns None → 401.
        r = client.post(f"/api/requests/{test_request.id}/vote")
        assert r.status_code == 401
        bypass = Settings(env="development", dev_auth_bypass=True)
        with patch.object(config, "get_settings", lambda: bypass):
            r2 = client.post(f"/api/requests/{test_request.id}/vote")
        # Identity resolved by the bypass → NOT 401 (200 vote, or a post-identity
        # votability status — never the "guest identity required" 401).
        assert r2.status_code != 401, r2.text
