"""The test harness's frozen clock and data factories (conftest)."""

from datetime import timedelta

import pytest

import app.services.human_verification  # noqa: F401  (imports utcnow by name)
from app.core import time as app_time


def test_clock_freezes_app_time(clock):
    first = app_time.utcnow()
    assert app_time.utcnow() == first == clock.now


def test_clock_reaches_modules_that_imported_utcnow_by_name(clock):
    from app.services import human_verification

    assert human_verification.utcnow() == clock.now


def test_clock_covers_sqlalchemy_column_defaults(clock, make_guest):
    """Column defaults captured utcnow at import; freezegun still freezes them."""
    guest = make_guest()
    assert guest.created_at == clock.now


def test_clock_freezes_monotonic_time_for_rate_limits(clock):
    import time

    before = time.monotonic()
    clock.advance(5)
    assert time.monotonic() - before == pytest.approx(5)


def test_clock_advance_moves_time_forward(clock):
    start = clock.now
    clock.advance(3.5)
    assert app_time.utcnow() - start == timedelta(seconds=3.5)


def test_make_user_gives_unique_committed_users(make_user):
    a, b = make_user(), make_user(role="admin")
    assert a.id and b.id and a.username != b.username
    assert b.role == "admin"


def test_make_event_uses_the_frozen_clock_for_expiry(make_event, clock):
    event = make_event()
    assert event.expires_at == clock.now + timedelta(hours=6)


def test_unknown_markers_are_rejected(tmp_path):
    """strict_markers (pyproject): an unregistered marker fails collection."""
    import subprocess
    import sys

    (tmp_path / "pytest.ini").write_text("[pytest]\nstrict_markers = true\n")
    (tmp_path / "test_x.py").write_text(
        "import pytest\n\n@pytest.mark.not_registered_marker\ndef test_x():\n    pass\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "not_registered_marker" in result.stdout + result.stderr


def test_make_guest_gives_unique_tokens(make_guest):
    a, b = make_guest(), make_guest()
    assert a.token != b.token and len(a.token) == 64


def test_make_request_belongs_to_an_event(make_request, make_event):
    event = make_event()
    request = make_request(event=event, song_title="Midnight City")
    assert request.event_id == event.id and request.song_title == "Midnight City"


def test_make_set_creates_a_set_through_the_api(make_set):
    assert isinstance(make_set("My Set"), int)


def test_frozen_request_reaches_a_router_that_has_a_datetime_parameter():
    """A frozen test that is the first to reach a router (a file run on its own) must work.

    FastAPI builds route parameter fields on a router's first request; built under freezegun
    they saw FakeDatetime and every request failed. The clock fixture builds them first.
    """
    from fastapi.testclient import TestClient
    from freezegun import freeze_time

    from app.main import create_app, no_background_lifespan
    from tests.conftest import _build_route_contexts_unfrozen

    fresh = create_app(lifespan_context=no_background_lifespan)
    _build_route_contexts_unfrozen(fresh)
    with freeze_time("2026-01-01 12:00:00", tick=False), TestClient(fresh) as c:
        # `since: datetime | None` is a query parameter of this route; no auth -> 401, not 500.
        assert c.get("/api/events/NOPE01/requests").status_code == 401
