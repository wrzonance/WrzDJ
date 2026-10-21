"""Public collection endpoint tests grouped by behavior."""

from app.core.time import utcnow
from app.models.guest import Guest
from tests.collect_public.helpers import _human_cookie_for

# ── Nickname uniqueness tests ──────────────────────────────────────────────


class TestNicknameUniqueness:
    """Tests for per-event nickname collision detection."""

    def _make_guest(self, db, token_suffix: str, verified: bool = False):
        """Build a guest. Always email-verified so the require_email_verified
        gate on collect endpoints lets them through — nickname uniqueness is
        an independent concern from email verification. The `verified` arg
        controls whether email_verified_at is set so 'claimed' detection works.
        """
        import hashlib

        from app.core.time import utcnow

        email = f"{token_suffix}@example.com"
        g = Guest(
            token="guest" + token_suffix.ljust(59, "0"),
            fingerprint_hash=f"fp_{token_suffix}",
            verified_email=email,
            email_hash=hashlib.sha256(email.encode()).hexdigest(),
            email_verified_at=utcnow() if verified else None,
            created_at=utcnow(),
            last_seen_at=utcnow(),
        )
        db.add(g)
        db.commit()
        db.refresh(g)
        return g

    def _human_cookie_for(self, guest_id: int) -> str:
        return _human_cookie_for(guest_id)

    def _set_guest_cookies(self, client, guest: Guest) -> None:
        """Replace the client cookie jar with one guest's identity cookies."""
        client.cookies.clear()
        client.cookies.set("wrzdj_guest", guest.token)
        client.cookies.set("wrzdj_human", self._human_cookie_for(guest.id))

    def test_available_nickname_succeeds(self, client, db, test_event):
        r = client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "UniqueNick"},
        )
        assert r.status_code == 200
        assert r.json()["nickname"] == "UniqueNick"

    def test_collision_unclaimed_returns_409_claimed_false(
        self, client, db, test_event, _default_guest_cookie
    ):
        # default guest (autouse) claims "Alex"
        client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "Alex"},
        )
        # Mark default guest unverified-after-claim so "claimed" returns False.
        # The autouse fixture pre-verifies for gate-pass; this test specifically
        # exercises the post-claim unverified state.
        _default_guest_cookie.email_verified_at = None
        db.commit()
        # second guest tries "Alex"
        guest2 = self._make_guest(db, "two")
        self._set_guest_cookies(client, guest2)
        r = client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "Alex"},
        )
        assert r.status_code == 409
        body = r.json()["detail"]
        assert body["code"] == "nickname_taken"
        assert body["claimed"] is False

    def test_collision_claimed_returns_409_claimed_true(self, client, db, test_event):
        # email-verified guest claims "Alex"
        verified_guest = self._make_guest(db, "verified", verified=True)
        self._set_guest_cookies(client, verified_guest)
        client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "Alex"},
        )
        # second guest tries same name
        guest2 = self._make_guest(db, "two")
        self._set_guest_cookies(client, guest2)
        r = client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "Alex"},
        )
        assert r.status_code == 409
        body = r.json()["detail"]
        assert body["code"] == "nickname_taken"
        assert body["claimed"] is True

    def test_self_collision_is_idempotent(self, client, db, test_event):
        client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "Alex"},
        )
        r = client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "Alex"},
        )
        assert r.status_code == 200

    def test_collision_is_case_insensitive(self, client, db, test_event):
        client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "Alex"},
        )
        for variant in ["alex", "ALEX", "aLeX"]:
            g = self._make_guest(db, variant)
            self._set_guest_cookies(client, g)
            r = client.post(
                f"/api/public/collect/{test_event.code}/profile",
                json={"nickname": variant},
            )
            assert r.status_code == 409, f"Expected 409 for variant '{variant}'"

    def test_race_condition_integrity_error_maps_to_409(self, client, db, test_event, monkeypatch):
        from sqlalchemy.exc import IntegrityError

        import app.api.collect as collect_api

        def raise_integrity(db, *, event_id, guest_id=None, nickname=None):
            raise IntegrityError("unique constraint", None, Exception())

        monkeypatch.setattr(collect_api, "upsert_profile", raise_integrity)

        r = client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "Alex"},
        )
        assert r.status_code == 409
        body = r.json()["detail"]
        assert body["code"] == "nickname_taken"
        assert body["claimed"] is False

    def test_null_nickname_skips_uniqueness_check(self, client, db, test_event):
        r = client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={},
        )
        assert r.status_code == 200


class TestProfileRejectsNameBeforeEmailGate:
    """Regression for #853: a name the server will refuse is rejected before the
    email gate, so a guest without a verified email is never sent through the
    email-code step only to have the name refused afterwards."""

    def _use_unverified_guest(self, client, db) -> None:
        guest = Guest(
            token="unverified" + "0" * 54,
            fingerprint_hash="fp_unverified",
            created_at=utcnow(),
            last_seen_at=utcnow(),
        )
        db.add(guest)
        db.commit()
        db.refresh(guest)
        client.cookies.clear()
        client.cookies.set("wrzdj_guest", guest.token)
        client.cookies.set("wrzdj_human", _human_cookie_for(guest.id))

    def test_profane_name_rejected_before_email_gate(self, client, db, test_event):
        self._use_unverified_guest(client, db)
        r = client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "FuckYou"},
        )
        assert r.status_code == 422
        assert "Please choose a different name" in r.text

    def test_malformed_name_rejected_before_email_gate(self, client, db, test_event):
        self._use_unverified_guest(client, db)
        r = client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "<script>"},
        )
        assert r.status_code == 422

    def test_taken_name_rejected_before_email_gate(self, client, db, test_event):
        client.post(f"/api/public/collect/{test_event.code}/profile", json={"nickname": "Alex"})
        self._use_unverified_guest(client, db)
        r = client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "alex"},
        )
        assert r.status_code == 409
        assert r.json()["detail"] == {"code": "nickname_taken", "claimed": True}

    def test_acceptable_name_still_requires_verified_email(self, client, db, test_event):
        self._use_unverified_guest(client, db)
        r = client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "DancingQueen"},
        )
        assert r.status_code == 403
        assert r.json()["detail"] == {"code": "email_verification_required"}
