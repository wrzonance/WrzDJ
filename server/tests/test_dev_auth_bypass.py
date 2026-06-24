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


class TestLeakedDevGuestCannotBackdoorProd:
    """Codex [P1]: the reserved dev guest token must be UNRESOLVABLE when the bypass is
    off, and the dev guest must not be pre-verified — so even if the row leaks into a
    production DB it can never become a backdoor."""

    def _req(self, token=None):
        from starlette.requests import Request

        headers = [(b"cookie", f"wrzdj_guest={token}".encode())] if token else []
        return Request({"type": "http", "headers": headers})

    def test_leaked_dev_token_rejected_when_bypass_off(self, db):
        from app.core.rate_limit import (
            _DEV_BYPASS_GUEST_TOKEN,
            _dev_bypass_guest_id,
            get_guest_id,
        )

        _dev_bypass_guest_id(db)  # simulate the dev guest row leaking into this DB
        # Default test settings → bypass off → the known token must NOT resolve.
        assert get_guest_id(self._req(_DEV_BYPASS_GUEST_TOKEN), db) is None

    def test_dev_token_resolves_when_bypass_on(self, db):
        from app.core.rate_limit import (
            _DEV_BYPASS_GUEST_TOKEN,
            _dev_bypass_guest_id,
            get_guest_id,
        )

        gid = _dev_bypass_guest_id(db)
        bypass = Settings(env="development", dev_auth_bypass=True)
        with patch.object(config, "get_settings", lambda: bypass):
            assert get_guest_id(self._req(_DEV_BYPASS_GUEST_TOKEN), db) == gid

    def test_normal_token_still_resolves_when_bypass_off(self, db):
        from app.core.rate_limit import get_guest_id
        from app.core.time import utcnow
        from app.models.guest import Guest

        g = Guest(token="normal-guest-token-aaaaaaaa", created_at=utcnow(), last_seen_at=utcnow())
        db.add(g)
        db.commit()
        db.refresh(g)
        assert get_guest_id(self._req("normal-guest-token-aaaaaaaa"), db) == g.id

    def test_dev_guest_is_not_pre_verified(self, db):
        from app.core.rate_limit import _DEV_BYPASS_GUEST_TOKEN, _dev_bypass_guest_id
        from app.models.guest import Guest

        _dev_bypass_guest_id(db)
        g = db.query(Guest).filter(Guest.token == _DEV_BYPASS_GUEST_TOKEN).first()
        assert g.verified_email is None and g.email_verified_at is None

    def test_identify_cannot_claim_leaked_dev_row(self, client, db):
        """/guest/identify must not let an attacker claim or re-tokenize a leaked dev
        guest row via its known cookie when the bypass is off (Codex P2 — that path
        does not go through get_guest_id)."""
        from app.core.rate_limit import _DEV_BYPASS_GUEST_TOKEN, _dev_bypass_guest_id
        from app.models.guest import Guest

        dev_id = _dev_bypass_guest_id(db)  # leaked dev row (no fingerprint, not verified)
        client.cookies.clear()
        client.cookies.set("wrzdj_guest", _DEV_BYPASS_GUEST_TOKEN)
        r = client.post("/api/public/guest/identify", json={"fingerprint_hash": "attacker-fp-zzz"})
        assert r.status_code == 200, r.text
        db.expire_all()
        dev = db.query(Guest).filter(Guest.token == _DEV_BYPASS_GUEST_TOKEN).first()
        # Attacker fingerprint must NOT be written onto the leaked dev row, and the
        # resolved identity must not be the dev row.
        assert dev.fingerprint_hash is None
        assert r.json().get("guest_id") != dev_id
