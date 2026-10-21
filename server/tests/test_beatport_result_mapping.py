"""Beatport provider response mapping contracts."""

from unittest.mock import MagicMock, patch

from app.services.providers.beatport_catalog import browse_beatport_tracks
from app.services.providers.beatport_mapping import beatport_track_to_result


def test_maps_complete_catalog_track_fields():
    result = beatport_track_to_result(
        {
            "id": 42,
            "name": "Track",
            "slug": "track",
            "mix_name": "Club Mix",
            "artists": [{"name": "First"}, {"name": "Second"}],
            "label": {"name": "Label"},
            "genre": {"name": "House"},
            "bpm": 126,
            "key": {"name": "8A"},
            "length": "5:30",
            "image": {"uri": "https://example.test/cover.jpg"},
            "new_release_date": "2025-04-03",
            "publish_date": "2025-04-01",
        }
    )

    assert result.model_dump() == {
        "track_id": "42",
        "title": "Track",
        "artist": "First, Second",
        "mix_name": "Club Mix",
        "label": "Label",
        "genre": "House",
        "bpm": 126,
        "key": "8A",
        "duration_seconds": 330,
        "cover_url": "https://example.test/cover.jpg",
        "beatport_url": "https://www.beatport.com/track/track/42",
        "release_date": "2025-04-03",
    }


def test_keeps_optional_field_fallbacks_for_sparse_track():
    result = beatport_track_to_result(
        {
            "id": 43,
            "artists": [{"name": "Artist"}],
            "label": None,
            "genre": None,
            "key": None,
            "image": None,
            "length": "unknown",
            "publish_date": "2024-02-01",
        }
    )

    assert result.track_id == "43"
    assert result.title == ""
    assert result.artist == "Artist"
    assert result.beatport_url == "https://www.beatport.com/track/untitled/43"
    assert result.duration_seconds is None
    assert result.cover_url is None
    assert result.release_date == "2024-02-01"


def test_supports_request_id_fallback_for_direct_track_lookup():
    result = beatport_track_to_result({}, fallback_track_id="44", url_track_id="44")

    assert result.track_id == "44"
    assert result.beatport_url == "https://www.beatport.com/track/untitled/44"


@patch("app.services.providers.beatport_catalog.httpx.Client")
@patch("app.services.providers.beatport_catalog.ensure_beatport_token", return_value=True)
def test_browse_normalizes_camelot_key_before_shared_mapping(
    _ensure_token, mock_client_class, db, test_user
):
    test_user.beatport_access_token = "beatport-test-token"
    response = MagicMock()
    response.json.return_value = {
        "results": [
            {
                "id": 45,
                "name": "Browse Track",
                "slug": "browse-track",
                "artists": [{"name": "Artist"}],
                "key": {"camelot_number": 8, "camelot_letter": "A"},
            }
        ]
    }
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get.return_value = response
    mock_client_class.return_value = client

    results = browse_beatport_tracks(db, test_user, genre_id=1)

    assert len(results) == 1
    assert results[0].key == "8A"
    assert results[0].track_id == "45"
