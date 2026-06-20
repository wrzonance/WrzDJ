"""Kiosk song-search / submit under human-verification enforcement (issue #514).

A DJ-paired kiosk is a trusted physical device: it holds a server-validated
`session_token`, sent as the `X-Kiosk-Session` header (the same one it already
uses to poll its event assignment). Like the authenticated event owner, an
*active* kiosk paired to the event must bypass the guest human-verification
gate — otherwise kiosk search/submit returns 403 in production once enforcement
is on, which is exactly the bug PR #513 left behind (it fixed the older 401 from
the DJ-only /api/search, but the kiosk then hit the 403 human gate instead).

The bypass is scoped to the kiosk's assigned event so one kiosk's token can't
vouch for a different event, and only `active` kiosks qualify.
"""

from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.kiosk import Kiosk
from app.models.system_settings import SystemSettings
from app.schemas.search import SearchResult

KIOSK_HEADER = "X-Kiosk-Session"

SPOTIFY_RESULT = SearchResult(
    title="Strobe",
    artist="deadmau5",
    album="For Lack of a Better Name",
    popularity=72,
    spotify_id="sp_strobe",
    source="spotify",
)


def _enforce(db: Session) -> None:
    """Turn human-verification enforcement ON (the production posture)."""
    sys_settings = db.query(SystemSettings).filter_by(id=1).first()
    if sys_settings is None:
        sys_settings = SystemSettings(id=1, human_verification_enforced=True)
        db.add(sys_settings)
    else:
        sys_settings.human_verification_enforced = True
    db.commit()


def _make_kiosk(
    db: Session,
    *,
    session_token: str,
    event_code: str | None,
    status: str = "active",
    pair_code: str,
) -> Kiosk:
    kiosk = Kiosk(
        pair_code=pair_code,
        session_token=session_token,
        event_code=event_code,
        status=status,
        pair_expires_at=utcnow() + timedelta(hours=1),
    )
    db.add(kiosk)
    db.commit()
    db.refresh(kiosk)
    return kiosk


class TestKioskSessionBypassesHumanGate:
    @patch("app.services.spotify.search_songs")
    def test_search_with_active_kiosk_session_bypasses_enforced_gate(
        self, mock_search, client: TestClient, db: Session, test_event: Event
    ):
        _enforce(db)
        mock_search.return_value = [SPOTIFY_RESULT]
        _make_kiosk(
            db, session_token="kiosk-tok-search", event_code=test_event.code, pair_code="KSK001"
        )

        # The kiosk reaches the event via its public join_code (its display URL),
        # never the collection code — exactly like the real device.
        response = client.get(
            f"/api/events/{test_event.join_code}/search?q=deadmau5",
            headers={KIOSK_HEADER: "kiosk-tok-search"},
        )

        assert response.status_code == 200
        assert response.json()[0]["title"] == "Strobe"

    def test_submit_with_active_kiosk_session_bypasses_enforced_gate(
        self, client: TestClient, db: Session, test_event: Event
    ):
        _enforce(db)
        _make_kiosk(
            db, session_token="kiosk-tok-submit", event_code=test_event.code, pair_code="KSK002"
        )

        response = client.post(
            f"/api/events/{test_event.join_code}/requests",
            json={
                "title": "Strobe",
                "artist": "deadmau5",
                "source": "spotify",
                "source_url": "https://open.spotify.com/track/x",
            },
            headers={KIOSK_HEADER: "kiosk-tok-submit"},
        )

        assert response.status_code in (200, 201)


class TestKioskBypassIsScoped:
    """The bypass must not become a blanket hole in the human gate."""

    @patch("app.services.spotify.search_songs")
    def test_search_unknown_kiosk_token_still_403(
        self, mock_search, client: TestClient, db: Session, test_event: Event
    ):
        _enforce(db)
        mock_search.return_value = [SPOTIFY_RESULT]

        response = client.get(
            f"/api/events/{test_event.join_code}/search?q=deadmau5",
            headers={KIOSK_HEADER: "no-such-kiosk"},
        )

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "human_verification_required"

    @patch("app.services.spotify.search_songs")
    def test_search_kiosk_paired_to_other_event_still_403(
        self, mock_search, client: TestClient, db: Session, test_event: Event
    ):
        _enforce(db)
        mock_search.return_value = [SPOTIFY_RESULT]
        _make_kiosk(db, session_token="kiosk-other-event", event_code="OTHER9", pair_code="KSK003")

        response = client.get(
            f"/api/events/{test_event.join_code}/search?q=deadmau5",
            headers={KIOSK_HEADER: "kiosk-other-event"},
        )

        assert response.status_code == 403

    @patch("app.services.spotify.search_songs")
    def test_search_pairing_status_kiosk_still_403(
        self, mock_search, client: TestClient, db: Session, test_event: Event
    ):
        _enforce(db)
        mock_search.return_value = [SPOTIFY_RESULT]
        _make_kiosk(
            db,
            session_token="kiosk-still-pairing",
            event_code=test_event.code,
            status="pairing",
            pair_code="KSK004",
        )

        response = client.get(
            f"/api/events/{test_event.join_code}/search?q=deadmau5",
            headers={KIOSK_HEADER: "kiosk-still-pairing"},
        )

        assert response.status_code == 403
