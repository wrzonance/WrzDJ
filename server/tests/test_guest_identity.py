"""Unit tests for guest identity resolution service."""

import json
import secrets
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.guest import Guest
from app.services.guest_identity import _ua_signals_match, identify_guest


def test_create_guest_new_visitor(db: Session):
    """No cookie, no fingerprint match -> new Guest created."""
    result = identify_guest(
        db,
        token_from_cookie=None,
        fingerprint_hash="brand_new_fp",
        fingerprint_components={"screen": "1170x2532"},
        user_agent="Mozilla/5.0 Safari/17.4",
    )
    assert result.guest_id is not None
    assert result.action == "create"
    assert result.token is not None
    assert len(result.token) == 64

    guest = db.query(Guest).filter(Guest.id == result.guest_id).one()
    assert guest.fingerprint_hash == "brand_new_fp"
    assert json.loads(guest.fingerprint_components) == {"screen": "1170x2532"}


def test_cookie_hit_returns_existing(db: Session, test_guest: Guest):
    """Valid cookie -> returns existing Guest, updates last_seen_at."""
    old_last_seen = test_guest.last_seen_at

    result = identify_guest(
        db,
        token_from_cookie=test_guest.token,
        fingerprint_hash="fp_test_hash_123",
        fingerprint_components={"screen": "1170x2532"},
        user_agent="Mozilla/5.0 Safari/17.4",
    )
    assert result.guest_id == test_guest.id
    assert result.action == "cookie_hit"
    assert result.token == test_guest.token

    db.refresh(test_guest)
    assert test_guest.last_seen_at >= old_last_seen


def test_cookie_hit_updates_ua(db: Session, test_guest: Guest):
    """Cookie hit from new UA -> field updated, guest_id unchanged."""
    result = identify_guest(
        db,
        token_from_cookie=test_guest.token,
        fingerprint_hash="fp_test_hash_123",
        fingerprint_components={"screen": "1170x2532"},
        user_agent="Mozilla/5.0 Chrome/125.0",
    )
    assert result.guest_id == test_guest.id

    db.refresh(test_guest)
    assert "Chrome" in test_guest.user_agent


def test_expired_token_ignored(db: Session):
    """Cookie present but token not in DB -> treated as new visitor."""
    result = identify_guest(
        db,
        token_from_cookie="nonexistent_token_" + "x" * 46,
        fingerprint_hash="some_fp_hash_1234",
        fingerprint_components={},
        user_agent="Mozilla/5.0 Safari/17.4",
    )
    assert result.action == "create"
    assert result.guest_id is not None


def test_fingerprint_drift_updates_hash(db: Session, test_guest: Guest):
    """Returning guest (cookie valid) with new fingerprint -> hash updated."""
    result = identify_guest(
        db,
        token_from_cookie=test_guest.token,
        fingerprint_hash="new_fp_after_browser_update",
        fingerprint_components={"screen": "1170x2532", "new_signal": True},
        user_agent="Mozilla/5.0 Safari/18.0",
    )
    assert result.guest_id == test_guest.id
    assert result.action == "cookie_hit"

    db.refresh(test_guest)
    assert test_guest.fingerprint_hash == "new_fp_after_browser_update"


def test_token_is_cryptographically_random(db: Session):
    """Generated tokens are 64 hex chars and unique."""
    tokens = set()
    for _ in range(100):
        result = identify_guest(
            db,
            token_from_cookie=None,
            fingerprint_hash=secrets.token_hex(16),
            fingerprint_components={},
            user_agent="Mozilla/5.0",
        )
        assert len(result.token) == 64
        assert result.token not in tokens
        tokens.add(result.token)


def test_fingerprint_components_stored_as_json(db: Session):
    """Components JSON saved on create."""
    components = {"screen": "390x844", "timezone": "America/New_York", "lang": "en-US"}
    result = identify_guest(
        db,
        token_from_cookie=None,
        fingerprint_hash="fp_components_test",
        fingerprint_components=components,
        user_agent="Mozilla/5.0",
    )
    guest = db.query(Guest).filter(Guest.id == result.guest_id).one()
    assert json.loads(guest.fingerprint_components) == components


CHROME_WIN = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/125.0 Safari/537.36"
CHROME_WIN_NEXT = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
CHROME_WIN_FAR = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
CHROME_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125.0 Safari/537.36"
)
SAFARI_IOS = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 Version/17.4 Mobile Safari/604.1"
)
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/124.0"
UNKNOWN_BOT = "PythonRequests/2.0"


@pytest.mark.parametrize(
    "stored,submitted,expected",
    [
        (CHROME_WIN, CHROME_WIN, True),  # exact same
        (CHROME_WIN, CHROME_WIN_NEXT, True),  # +1 version
        (CHROME_WIN, CHROME_WIN_FAR, False),  # +5 versions
        (CHROME_WIN, CHROME_MAC, False),  # different platform
        (CHROME_WIN, SAFARI_IOS, False),  # different family + platform
        (SAFARI_IOS, CHROME_MAC, False),  # different family
        (None, CHROME_WIN, False),  # stored=None
        (CHROME_WIN, UNKNOWN_BOT, False),  # unparseable submitted
        (UNKNOWN_BOT, CHROME_WIN, False),  # unparseable stored
        (FIREFOX_LINUX, FIREFOX_LINUX, True),  # firefox same
    ],
)
def test_ua_signals_match_strict(stored, submitted, expected):
    assert _ua_signals_match(stored, submitted) is expected


def test_create_when_ambiguous_match(db: Session):
    """Two guests with same FP within freshness window -> new guest, hint=True."""
    fp = "shared_fp_collision_xyz"
    now = utcnow()
    _chrome_linux = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36"
    for token_prefix in ("a", "b"):
        g = Guest(
            token=token_prefix * 64,
            fingerprint_hash=fp,
            fingerprint_components="{}",
            user_agent=_chrome_linux,
            created_at=now - timedelta(days=1),
            last_seen_at=now - timedelta(days=1),
        )
        db.add(g)
    db.commit()

    result = identify_guest(
        db,
        token_from_cookie=None,
        fingerprint_hash=fp,
        fingerprint_components={},
        user_agent=_chrome_linux,
    )
    assert result.action == "create"
    assert result.reconcile_hint is True
    assert result.rejection_reason == "ambiguous_match"
    assert db.query(Guest).filter(Guest.fingerprint_hash == fp).count() == 3


def test_create_when_verified_guest(db: Session):
    """Verified guest never auto-reconciles -> new guest, hint=True."""
    fp = "verified_user_fp"
    now = utcnow()
    _chrome_win = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/125.0 Safari/537.36"
    g = Guest(
        token="v" * 64,
        fingerprint_hash=fp,
        fingerprint_components="{}",
        user_agent=_chrome_win,
        created_at=now - timedelta(days=30),
        last_seen_at=now - timedelta(days=2),  # outside quiet period
        email_verified_at=now - timedelta(days=29),
        email_hash="x" * 64,
    )
    db.add(g)
    db.commit()

    result = identify_guest(
        db,
        token_from_cookie=None,
        fingerprint_hash=fp,
        fingerprint_components={},
        user_agent=_chrome_win,
    )
    assert result.action == "create"
    assert result.reconcile_hint is True
    assert result.rejection_reason == "verified_guest"
    assert result.guest_id != g.id


def test_create_when_concurrent_activity_5min(db: Session):
    """Existing guest active 5 min ago -> rejected, new guest created."""
    fp = "active_user_fp"
    now = utcnow()
    _chrome_win = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/125.0 Safari/537.36"
    g = Guest(
        token="c" * 64,
        fingerprint_hash=fp,
        fingerprint_components="{}",
        user_agent=_chrome_win,
        created_at=now - timedelta(hours=2),
        last_seen_at=now - timedelta(minutes=5),
    )
    db.add(g)
    db.commit()

    result = identify_guest(
        db,
        token_from_cookie=None,
        fingerprint_hash=fp,
        fingerprint_components={},
        user_agent=_chrome_win,
    )
    assert result.action == "create"
    assert result.reconcile_hint is True
    assert result.rejection_reason == "concurrent_activity"
    assert result.guest_id != g.id


def test_reconcile_when_quiet_period_passed_13h(db: Session):
    """Existing guest active 13 hours ago, all gates pass -> reconcile."""
    fp = "returning_user_fp"
    now = utcnow()
    _chrome_win = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/125.0 Safari/537.36"
    g = Guest(
        token="d" * 64,
        fingerprint_hash=fp,
        fingerprint_components="{}",
        user_agent=_chrome_win,
        created_at=now - timedelta(days=7),
        last_seen_at=now - timedelta(hours=13),
    )
    db.add(g)
    db.commit()
    original_id = g.id

    result = identify_guest(
        db,
        token_from_cookie=None,
        fingerprint_hash=fp,
        fingerprint_components={},
        user_agent=_chrome_win,
    )
    assert result.action == "reconcile"
    assert result.guest_id == original_id
    assert result.reconcile_hint is False
    assert result.token is not None


def test_create_when_ua_mismatch_phone_vs_pc(db: Session):
    """Same FP but different UA platform -> rejected, new guest created."""
    fp = "ua_collision_fp"
    now = utcnow()
    g = Guest(
        token="e" * 64,
        fingerprint_hash=fp,
        fingerprint_components="{}",
        user_agent="Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/125.0 Safari/537.36",
        created_at=now - timedelta(days=2),
        last_seen_at=now - timedelta(days=1),  # outside quiet period
    )
    db.add(g)
    db.commit()

    result = identify_guest(
        db,
        token_from_cookie=None,
        fingerprint_hash=fp,
        fingerprint_components={},
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
            "AppleWebKit/605.1.15 Version/17.4 Mobile Safari/604.1"
        ),
    )
    assert result.action == "create"
    assert result.reconcile_hint is True
    assert result.rejection_reason == "ua_mismatch"
    assert result.guest_id != g.id


def test_stale_match_excluded_from_reconcile_pool(db: Session):
    """Match older than 90 days is filtered out at query level -> no rejection reason."""
    fp = "stale_user_fp"
    now = utcnow()
    _chrome_win = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    g = Guest(
        token="f" * 64,
        fingerprint_hash=fp,
        fingerprint_components="{}",
        user_agent=_chrome_win,
        created_at=now - timedelta(days=120),
        last_seen_at=now - timedelta(days=91),  # stale
    )
    db.add(g)
    db.commit()

    result = identify_guest(
        db,
        token_from_cookie=None,
        fingerprint_hash=fp,
        fingerprint_components={},
        user_agent=_chrome_win,
    )
    assert result.action == "create"
    assert result.reconcile_hint is False
    assert result.rejection_reason is None
    assert result.guest_id != g.id


def test_identify_response_includes_reconcile_hint(client: TestClient, db: Session):
    """API response always includes reconcile_hint key (default false for fresh visitors)."""
    response = client.post(
        "/api/public/guest/identify",
        json={"fingerprint_hash": "fresh_fp_for_api_test", "fingerprint_components": {}},
    )
    assert response.status_code == 200
    body = response.json()
    assert "guest_id" in body
    assert "action" in body
    assert "reconcile_hint" in body
    assert body["reconcile_hint"] is False  # no FP match exists


def test_identify_does_not_leak_rejection_reason_to_client(client: TestClient, db: Session):
    """Even when reconciliation is rejected, rejection_reason MUST NOT be in response."""
    fp = "leak_test_fp"
    now = utcnow()
    g = Guest(
        token="z" * 64,
        fingerprint_hash=fp,
        fingerprint_components="{}",
        user_agent=("Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/125.0 Safari/537.36"),
        created_at=now - timedelta(days=1),
        last_seen_at=now - timedelta(minutes=5),  # triggers concurrent_activity
    )
    db.add(g)
    db.commit()

    response = client.post(
        "/api/public/guest/identify",
        json={"fingerprint_hash": fp, "fingerprint_components": {}},
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/125.0 Safari/537.36"
            ),
        },
    )
    body = response.json()
    assert body["reconcile_hint"] is True
    assert "rejection_reason" not in body
    assert "existing_guest" not in body


def test_resolve_guest_by_token_follows_tombstone_only_inside_cookie_window(db: Session):
    """#932: a merged-away token resolves to the survivor for guest_cookie_max_age_seconds
    after the merge, then to None (never to the tombstone itself)."""
    from datetime import timedelta

    from app.core.config import get_settings
    from app.core.time import utcnow
    from app.services.guest_identity import resolve_guest_by_token
    from app.services.guest_merge import merge_guests

    window = timedelta(seconds=get_settings().guest_cookie_max_age_seconds)
    source = Guest(token="s" * 64, created_at=utcnow(), last_seen_at=utcnow())
    target = Guest(token="t" * 64, created_at=utcnow(), last_seen_at=utcnow())
    db.add_all([source, target])
    db.commit()
    merge_guests(db, source_guest_id=source.id, target_guest_id=target.id)

    assert resolve_guest_by_token(db, "s" * 64).id == target.id

    source.merged_at = utcnow() - window - timedelta(seconds=1)
    db.commit()
    assert resolve_guest_by_token(db, "s" * 64) is None
    assert resolve_guest_by_token(db, "t" * 64).id == target.id


def test_fingerprint_reconcile_never_lands_on_a_tombstone(db: Session):
    """#932: a racing identify can write a fingerprint back onto a tombstone row. Cookieless
    reconciliation must skip it: a new guest is created and the tombstone token is untouched."""
    from datetime import timedelta

    from app.core.time import utcnow

    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/125.0 Safari/537.36"
    survivor = Guest(token="v" * 64, created_at=utcnow(), last_seen_at=utcnow())
    db.add(survivor)
    db.commit()
    tomb = Guest(
        token="w" * 64,
        fingerprint_hash="tomb_fp_hash_1234",
        user_agent=ua,
        merged_into_guest_id=survivor.id,
        merged_at=utcnow(),
        created_at=utcnow() - timedelta(days=2),
        last_seen_at=utcnow() - timedelta(days=1),
    )
    db.add(tomb)
    db.commit()

    result = identify_guest(
        db,
        token_from_cookie=None,
        fingerprint_hash="tomb_fp_hash_1234",
        fingerprint_components={},
        user_agent=ua,
    )

    assert result.action == "create"
    assert result.guest_id not in (tomb.id, survivor.id)
    db.refresh(tomb)
    assert tomb.token == "w" * 64
