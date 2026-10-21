"""Public collection endpoint tests grouped by behavior."""

from datetime import datetime

from app.models.event import Event
from app.models.guest import Guest
from tests.collect_public.helpers import _enable_collection


def test_leaderboard_row_includes_enrichment_fields(client, db, test_event: Event):
    """Leaderboard rows expose bpm/musical_key/genre when set on the request."""
    from app.models.request import Request, RequestStatus

    _enable_collection(db, test_event)
    req = Request(
        event_id=test_event.id,
        song_title="Levels",
        artist="Avicii",
        source="beatport",
        status=RequestStatus.NEW.value,
        vote_count=3,
        dedupe_key="levels_avicii_enriched",
        submitted_during_collection=True,
        bpm=128.0,
        musical_key="8A",
        genre="Progressive House",
    )
    db.add(req)
    db.commit()

    r = client.get(f"/api/public/collect/{test_event.code}/leaderboard?tab=all")
    assert r.status_code == 200
    rows = r.json()["requests"]
    assert len(rows) == 1
    assert rows[0]["bpm"] == 128
    assert rows[0]["musical_key"] == "8A"
    assert rows[0]["genre"] == "Progressive House"


def test_leaderboard_row_enrichment_fields_null_when_missing(client, db, test_event: Event):
    from app.models.request import Request, RequestStatus

    _enable_collection(db, test_event)
    req = Request(
        event_id=test_event.id,
        song_title="Unknown",
        artist="Someone",
        source="spotify",
        status=RequestStatus.NEW.value,
        dedupe_key="unknown_someone_collect",
        submitted_during_collection=True,
    )
    db.add(req)
    db.commit()

    r = client.get(f"/api/public/collect/{test_event.code}/leaderboard?tab=all")
    assert r.status_code == 200
    rows = r.json()["requests"]
    assert len(rows) == 1
    assert rows[0]["bpm"] is None
    assert rows[0]["musical_key"] is None
    assert rows[0]["genre"] is None


def test_collect_submit_triggers_enrichment(client, db, test_event: Event):
    """Submitting a pick fires enrich_request_metadata as a background task."""
    from unittest.mock import patch

    _enable_collection(db, test_event)

    # The shared enrich_with_fresh_session helper (orchestrator) is what the collect
    # background task runs; patch enrichment there so the task is a no-op + observable.
    with patch("app.services.sync.orchestrator.enrich_request_metadata") as mock_enrich:
        r = client.post(
            f"/api/public/collect/{test_event.code}/requests",
            json={
                "song_title": "Levels",
                "artist": "Avicii",
                "source": "spotify",
            },
        )

    assert r.status_code == 201
    assert r.json()["is_duplicate"] is False
    mock_enrich.assert_called_once()
    _, request_id = mock_enrich.call_args[0]
    assert isinstance(request_id, int)


def test_my_picks_includes_enrichment_fields(
    client, db, test_event: Event, _default_guest_cookie: Guest
):
    """my_picks response populates bpm/musical_key/genre from enriched requests."""
    from app.models.request import Request, RequestStatus

    _enable_collection(db, test_event)
    req = Request(
        event_id=test_event.id,
        song_title="Levels",
        artist="Avicii",
        source="beatport",
        status=RequestStatus.NEW.value,
        dedupe_key="levels_avicii_mypicks",
        submitted_during_collection=True,
        guest_id=_default_guest_cookie.id,
        bpm=128.0,
        musical_key="8A",
        genre="Progressive House",
    )
    db.add(req)
    db.commit()

    r = client.get(f"/api/public/collect/{test_event.code}/profile/me")
    assert r.status_code == 200
    submitted = r.json()["submitted"]
    assert len(submitted) == 1
    assert submitted[0]["bpm"] == 128
    assert submitted[0]["musical_key"] == "8A"
    assert submitted[0]["genre"] == "Progressive House"


# ── Enrich-preview tests ──────────────────────────────────────────────────────


def test_enrich_preview_returns_nulls_without_beatport_token(client, db, test_event: Event):
    """When the DJ has no Beatport token, all results have null bpm/key/genre."""
    _enable_collection(db, test_event)
    dj = test_event.created_by
    dj.beatport_access_token = None
    db.commit()

    r = client.post(
        f"/api/public/collect/{test_event.code}/enrich-preview",
        json={"items": [{"title": "Levels", "artist": "Avicii"}]},
    )
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 1
    assert results[0]["title"] == "Levels"
    assert results[0]["artist"] == "Avicii"
    assert results[0]["bpm"] is None
    assert results[0]["key"] is None
    assert results[0]["genre"] is None


def test_enrich_preview_returns_bpm_from_beatport(client, db, test_event: Event):
    """When Beatport search returns a match, bpm/key/genre are populated."""
    from unittest.mock import MagicMock, patch

    _enable_collection(db, test_event)

    dj = test_event.created_by
    dj.beatport_access_token = "fake_token"  # nosec B106
    db.commit()

    mock_match = MagicMock()
    mock_match.title = "Levels"
    mock_match.artist = "Avicii"
    mock_match.bpm = 128
    mock_match.key = "8A"
    mock_match.genre = "Progressive House"
    mock_match.mix_name = "Original Mix"

    with (
        patch("app.api.collect.search_beatport_tracks", return_value=[mock_match]),
        patch("app.api.collect.find_best_match", return_value=mock_match),
    ):
        r = client.post(
            f"/api/public/collect/{test_event.code}/enrich-preview",
            json={"items": [{"title": "Levels", "artist": "Avicii"}]},
        )

    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 1
    assert results[0]["bpm"] == 128
    assert results[0]["key"] == "8A"
    assert results[0]["genre"] == "Progressive House"


def test_enrich_preview_preserves_remix_intent(client, db, test_event: Event):
    """The preview must derive prefer_original from the title (#551/#553): a named-remix
    query must NOT be matched with prefer_original=True (which would favour the original
    version's BPM/key), matching the enrichment + recommendation paths."""
    from unittest.mock import MagicMock, patch

    _enable_collection(db, test_event)
    dj = test_event.created_by
    dj.beatport_access_token = "fake_token"  # nosec B106
    db.commit()

    match = MagicMock(
        title="Surrender (Hardstyle Remix)", artist="Darude", bpm=165, key=None, genre=None
    )
    with (
        patch("app.api.collect.search_beatport_tracks", return_value=[match]),
        patch("app.api.collect.find_best_match", return_value=match) as spy,
    ):
        # Remix query → prefer_original must be False.
        client.post(
            f"/api/public/collect/{test_event.code}/enrich-preview",
            json={"items": [{"title": "Surrender (Hardstyle Remix)", "artist": "Darude"}]},
        )
        assert spy.call_args.kwargs["prefer_original"] is False

        # Plain query → prefer_original stays True.
        spy.reset_mock()
        client.post(
            f"/api/public/collect/{test_event.code}/enrich-preview",
            json={"items": [{"title": "Surrender", "artist": "Darude"}]},
        )
        assert spy.call_args.kwargs["prefer_original"] is True


def test_enrich_preview_caps_at_10_items(client, db, test_event: Event):
    """Requests with >10 items are silently capped — only first 10 processed."""
    _enable_collection(db, test_event)
    dj = test_event.created_by
    dj.beatport_access_token = None
    db.commit()

    items = [{"title": f"Song {i}", "artist": f"Artist {i}"} for i in range(15)]
    r = client.post(
        f"/api/public/collect/{test_event.code}/enrich-preview",
        json={"items": items},
    )
    assert r.status_code == 200
    assert len(r.json()["results"]) == 10


def test_enrich_preview_404_for_unknown_event(client):
    r = client.post(
        "/api/public/collect/ZZZZZZ/enrich-preview",
        json={"items": [{"title": "X", "artist": "Y"}]},
    )
    assert r.status_code == 404


def test_enrich_preview_returns_nulls_when_beatport_raises(client, db, test_event: Event):
    """When Beatport search raises an exception, result fields are null (best-effort)."""
    from unittest.mock import patch

    _enable_collection(db, test_event)
    dj = test_event.created_by
    dj.beatport_access_token = "fake_token"  # nosec B106
    db.commit()

    with patch("app.api.collect.search_beatport_tracks", side_effect=Exception("timeout")):
        r = client.post(
            f"/api/public/collect/{test_event.code}/enrich-preview",
            json={"items": [{"title": "Levels", "artist": "Avicii"}]},
        )

    assert r.status_code == 200
    result = r.json()["results"][0]
    assert result["bpm"] is None
    assert result["key"] is None
    assert result["genre"] is None


def test_leaderboard_row_requester_verified_true(client, db, test_event: Event):
    """requester_verified is True when guest has email_verified_at set."""
    from app.models.guest import Guest
    from app.models.request import Request, RequestStatus

    _enable_collection(db, test_event)
    guest = Guest(
        token="verified_leaderboard_test",
        email_verified_at=datetime(2026, 5, 1),
    )
    db.add(guest)
    db.flush()
    req = Request(
        event_id=test_event.id,
        song_title="Verified Track",
        artist="Verified Artist",
        source="spotify",
        status=RequestStatus.NEW.value,
        vote_count=2,
        dedupe_key="verified_lb_test",
        submitted_during_collection=True,
        guest_id=guest.id,
        nickname="VerifiedUser",
    )
    db.add(req)
    db.commit()

    r = client.get(f"/api/public/collect/{test_event.code}/leaderboard?tab=all")
    assert r.status_code == 200
    rows = r.json()["requests"]
    assert len(rows) == 1
    assert rows[0]["requester_verified"] is True


def test_leaderboard_row_requester_verified_false_no_guest(client, db, test_event: Event):
    """requester_verified is False when request has no guest_id."""
    from app.models.request import Request, RequestStatus

    _enable_collection(db, test_event)
    req = Request(
        event_id=test_event.id,
        song_title="Anon Track",
        artist="Anon Artist",
        source="spotify",
        status=RequestStatus.NEW.value,
        vote_count=1,
        dedupe_key="anon_lb_test",
        submitted_during_collection=True,
    )
    db.add(req)
    db.commit()

    r = client.get(f"/api/public/collect/{test_event.code}/leaderboard?tab=all")
    assert r.status_code == 200
    rows = r.json()["requests"]
    assert len(rows) == 1
    assert rows[0]["requester_verified"] is False
