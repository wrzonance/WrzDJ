"""Public search availability follows the providers that can actually run."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.system_settings import SystemSettings


@pytest.mark.parametrize(
    ("beatport_linked", "event_beatport_enabled"),
    [(False, True), (True, False)],
    ids=["owner-not-linked", "event-disabled"],
)
def test_search_is_unavailable_when_beatport_cannot_run(
    client: TestClient,
    db: Session,
    test_event: Event,
    beatport_linked: bool,
    event_beatport_enabled: bool,
    monkeypatch: pytest.MonkeyPatch,
):
    """Global Beatport enablement alone does not make a provider available."""
    from app.services.providers import beatport

    settings = SystemSettings(
        id=1,
        spotify_enabled=False,
        tidal_enabled=False,
        beatport_enabled=True,
    )
    db.add(settings)
    owner = test_event.created_by
    owner.beatport_access_token = "linked-token" if beatport_linked else None
    test_event.beatport_sync_enabled = event_beatport_enabled
    db.flush()

    monkeypatch.setattr(
        beatport,
        "search_beatport_tracks",
        lambda *_args, **_kwargs: pytest.fail("Beatport must not run when it is unavailable"),
    )
    response = client.get(f"/api/events/{test_event.code}/search?q=strobe")

    assert response.status_code == 503
    assert response.json()["detail"] == "Song search is currently unavailable"
