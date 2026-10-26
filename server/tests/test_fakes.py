"""The provider fakes behave like the services on good and bad days (tests/fakes).

Each case drives the app's real client code over the fake wire, so a test proves both the
fake and how the app handles that day.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import requests
from sqlalchemy.orm import Session

from app.models.user import User
from app.services import beatport, listenbrainz, tidal
from tests.fakes.providers import LISTENBRAINZ_POPULARITY

MBIDS = ["a74b1b7f-71a5-4011-9441-d0b5e4122711", "8bfac288-ccc5-448d-9573-c33ea2aa5c30"]


class TestFakeWire:
    def test_httpx_gets_the_registered_json(self, fake_http):
        fake_http.add("GET", "https://api.example.test/v1/thing", json={"ok": True})
        r = httpx.get("https://api.example.test/v1/thing?x=1")
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        assert fake_http.called("GET", "https://api.example.test/v1/thing") == 1

    def test_requests_gets_the_registered_status_and_headers(self, fake_http):
        fake_http.add("GET", "https://api.example.test/*", status=429, headers={"Retry-After": "2"})
        r = requests.get("https://api.example.test/anything", timeout=1)
        assert r.status_code == 429
        assert r.headers["Retry-After"] == "2"

    def test_newest_route_wins_so_tests_can_layer_a_bad_day(self, fake_http):
        fake_http.add("GET", "https://api.example.test/v1/thing", json={"ok": True})
        fake_http.add("GET", "https://api.example.test/v1/thing", status=500)
        assert httpx.get("https://api.example.test/v1/thing").status_code == 500

    @pytest.mark.parametrize(
        ("raises", "httpx_error", "requests_error"),
        [
            ("timeout", httpx.ReadTimeout, requests.exceptions.ReadTimeout),
            ("connect", httpx.ConnectError, requests.exceptions.ConnectionError),
        ],
    )
    def test_timeouts_and_refused_connections(self, fake_http, raises, httpx_error, requests_error):
        fake_http.add("GET", "https://api.example.test/*", raises=raises)
        with pytest.raises(httpx_error):
            httpx.get("https://api.example.test/slow")
        with pytest.raises(requests_error):
            requests.get("https://api.example.test/slow", timeout=1)


class TestListenBrainzDays:
    def test_ok_day(self, listenbrainz_popular):
        data = listenbrainz.fetch_artist_popularity(MBIDS)
        assert set(data) == set(MBIDS)
        assert data[MBIDS[0]]["total_user_count"] == 5000

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_error_status_degrades_to_no_data(self, fake_http, status):
        fake_http.add("POST", LISTENBRAINZ_POPULARITY, status=status, json={"error": "nope"})
        assert listenbrainz.fetch_artist_popularity(MBIDS) == {}

    def test_timeout_degrades_to_no_data(self, fake_http):
        fake_http.add("POST", LISTENBRAINZ_POPULARITY, raises="timeout")
        assert listenbrainz.fetch_artist_popularity(MBIDS) == {}


class TestBeatportDays:
    @pytest.fixture
    def bp_user(self, db: Session, test_user: User) -> User:
        test_user.beatport_access_token = "fake-access"
        test_user.beatport_refresh_token = "fake-refresh"
        test_user.beatport_token_expires_at = datetime.now(UTC) + timedelta(hours=1)
        db.commit()
        return test_user

    def test_streaming_subscription_is_read(self, db, bp_user, beatport_up):
        assert beatport.fetch_subscription_type(db, bp_user) == "streaming"

    def test_expired_login_401_gives_no_subscription(self, db, bp_user, beatport_up):
        beatport_up.add(
            "GET", "https://api.beatport.com/v4/my/account/", status=401, json={"detail": "expired"}
        )
        assert beatport.fetch_subscription_type(db, bp_user) is None


class TestTidalDays:
    @pytest.fixture
    def tidal_user(self, db: Session, test_user: User) -> User:
        test_user.tidal_access_token = "fake-access"
        test_user.tidal_refresh_token = "fake-refresh"
        test_user.tidal_token_expires_at = datetime.now(UTC) + timedelta(hours=1)
        db.commit()
        return test_user

    def test_connected_account_loads_a_session(self, db, tidal_user, tidal_connected):
        session = tidal.get_tidal_session(db, tidal_user)
        assert session is not None
        assert session.country_code == "US"

    def test_tidal_down_gives_no_session(self, db, tidal_user, tidal_down):
        assert tidal.get_tidal_session(db, tidal_user) is None
