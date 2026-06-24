"""Cache-aside dual-write of enrichment into the master tracks store (#541).

`enrich_request_metadata` must:
  * write the global `tracks` row once per unique recording (provenance-tagged),
  * reuse a complete store row with ZERO provider calls on the next request of
    the same song (the dedupe win),
  * still dual-write genre/bpm/musical_key onto the Request (current UI),
  * call Soundcharts for audio features only behind the dark gate + an ISRC.

Monkeypatch note: provider clients are LOCAL-imported inside
`enrich_request_metadata`, so they are patched on their SOURCE module
(`app.services.beatport`, `app.services.soundcharts`). `lookup_artist_genre`
is top-imported into the pipeline, so it is patched on the pipeline module.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.models.user import User
from app.services.setbuilder.pool import dedupe_signature
from app.services.sync.enrichment_pipeline import enrich_request_metadata
from app.services.tracks.store import get_track


@pytest.fixture
def bp_user(db: Session) -> User:
    """A DJ user with a Beatport token (so the Beatport block is entered)."""
    from app.services.auth import get_password_hash

    user = User(
        username="enrich_store_user",
        password_hash=get_password_hash("testpassword123"),
        beatport_access_token="fake_bp_token",
        tidal_access_token="fake_tidal_token",
        tidal_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_event(db: Session, owner: User, code: str, join_code: str) -> Event:
    event = Event(
        code=code,
        join_code=join_code,
        name=f"Event {code}",
        created_by_user_id=owner.id,
        expires_at=datetime.now(UTC) + timedelta(hours=6),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def _make_request(db: Session, event: Event, title: str, artist: str, dedupe: str) -> Request:
    request = Request(
        event_id=event.id,
        song_title=title,
        artist=artist,
        source="spotify",
        status=RequestStatus.ACCEPTED.value,
        dedupe_key=dedupe,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


def _beatport_hit(title: str, artist: str):
    from app.schemas.beatport import BeatportSearchResult

    return BeatportSearchResult(
        track_id="123",
        title=title,
        artist=artist,
        genre="Progressive House",
        bpm=128,
        key="F Minor",
    )


def _settings_stub(*, enabled: bool):
    """Minimal settings stand-in carrying only the audio-features gate."""
    from unittest.mock import MagicMock

    return MagicMock(soundcharts_audio_features_enabled=enabled)


class _Spy:
    """Callable returning a fixed value, counting invocations."""

    def __init__(self, return_value):
        self.return_value = return_value
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.return_value


def test_enrich_once_reuse_everywhere(db: Session, bp_user: User, monkeypatch):
    """HEADLINE REGRESSION: enrich song X at event A, then reuse at event B.

    The second enrichment must hit the store (zero provider calls) and still
    populate Request B's genre/bpm/musical_key from the cached row.
    """
    event_a = _make_event(db, bp_user, "STOREA", "STRAAA")
    event_b = _make_event(db, bp_user, "STOREB", "STRBBB")

    title, artist = "Strobe", "deadmau5"
    request_a = _make_request(db, event_a, title, artist, "store_dedupe_a")

    genre_spy = _Spy(None)  # MusicBrainz misses; Beatport backfills genre
    beatport_spy = _Spy([_beatport_hit(title, artist)])
    tidal_spy = _Spy([])

    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", genre_spy)
    monkeypatch.setattr("app.services.beatport.search_beatport_tracks", beatport_spy)
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", tidal_spy)

    enrich_request_metadata(db, request_a.id)

    # Store row written for the recording, fully populated + provenance-tagged.
    sig = dedupe_signature(artist, title)
    track = get_track(db, signature=sig)
    assert track is not None
    assert track.genre == "Progressive House"
    assert track.bpm == 128.0
    assert track.musical_key == "4A"  # F Minor -> 4A Camelot
    assert track.provenance["genre"]["source"] == "beatport"
    assert track.provenance["bpm"]["source"] == "beatport"

    db.refresh(request_a)
    assert request_a.genre == "Progressive House"
    assert request_a.bpm == 128.0
    assert request_a.musical_key == "4A"

    # Second event requests the SAME song — reset provider counters.
    beatport_calls_before = beatport_spy.calls
    genre_calls_before = genre_spy.calls
    tidal_calls_before = tidal_spy.calls

    request_b = _make_request(db, event_b, title, artist, "store_dedupe_b")
    enrich_request_metadata(db, request_b.id)

    # ZERO new provider calls — the dedupe win.
    assert beatport_spy.calls == beatport_calls_before
    assert genre_spy.calls == genre_calls_before
    assert tidal_spy.calls == tidal_calls_before

    # Request B populated entirely from the store.
    db.refresh(request_b)
    assert request_b.genre == "Progressive House"
    assert request_b.bpm == 128.0
    assert request_b.musical_key == "4A"


def test_provenance_recorded_per_field(db: Session, bp_user: User, monkeypatch):
    """Each field is recorded with the source that resolved it."""
    event = _make_event(db, bp_user, "PROVEN", "PRVNNN")
    request = _make_request(db, event, "Strobe", "deadmau5", "prov_dedupe")

    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline.lookup_artist_genre",
        _Spy("electronic"),  # MusicBrainz provides genre
    )
    monkeypatch.setattr(
        "app.services.beatport.search_beatport_tracks",
        _Spy([_beatport_hit("Strobe", "deadmau5")]),  # Beatport provides bpm/key
    )
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", _Spy([]))

    enrich_request_metadata(db, request.id)

    sig = dedupe_signature("deadmau5", "Strobe")
    track = get_track(db, signature=sig)
    assert track is not None
    assert track.genre == "electronic"
    assert track.provenance["genre"]["source"] == "musicbrainz"
    assert track.provenance["bpm"]["source"] == "beatport"
    assert track.provenance["musical_key"]["source"] == "beatport"


def test_dual_write_preserved_on_miss(db: Session, bp_user: User, monkeypatch):
    """On the miss path the Request columns are still populated (current UI)."""
    event = _make_event(db, bp_user, "DUALWR", "DUALWW")
    request = _make_request(db, event, "Strobe", "deadmau5", "dual_dedupe")

    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr(
        "app.services.beatport.search_beatport_tracks",
        _Spy([_beatport_hit("Strobe", "deadmau5")]),
    )
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", _Spy([]))

    enrich_request_metadata(db, request.id)

    db.refresh(request)
    assert request.genre == "Progressive House"
    assert request.bpm == 128.0
    assert request.musical_key == "4A"


def test_energy_gate_off_does_not_call_soundcharts(db: Session, bp_user: User, monkeypatch):
    """Default (gate off): Soundcharts feature fn is never called; energy stays None."""
    event = _make_event(db, bp_user, "ENGOFF", "ENGOFW")
    # Spotify source_url so an ISRC is discoverable.
    request = _make_request(db, event, "Strobe", "deadmau5", "energy_off")
    request.source_url = "https://open.spotify.com/track/abc123"
    db.commit()

    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr(
        "app.services.beatport.search_beatport_tracks",
        _Spy([_beatport_hit("Strobe", "deadmau5")]),
    )
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", _Spy([]))
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline._get_isrc_from_spotify",
        lambda url: "USABC1234567",
    )

    feature_spy = _Spy(None)
    monkeypatch.setattr("app.services.soundcharts.get_song_features_by_isrc", feature_spy)
    # Ensure the gate is off (default) for the pipeline's pre-call check.
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline.get_settings",
        lambda: _settings_stub(enabled=False),
    )

    enrich_request_metadata(db, request.id)

    assert feature_spy.calls == 0
    sig = dedupe_signature("deadmau5", "Strobe")
    track = get_track(db, signature=sig)
    assert track is not None
    assert track.energy is None


def test_energy_gate_on_writes_energy_with_provenance(db: Session, bp_user: User, monkeypatch):
    """Gate on + ISRC: Soundcharts adapter is called; energy written as 'soundcharts'."""
    from app.services.soundcharts import SoundchartsAudioFeatures

    event = _make_event(db, bp_user, "ENGON1", "ENGONW")
    request = _make_request(db, event, "Strobe", "deadmau5", "energy_on")
    request.source_url = "https://open.spotify.com/track/abc123"
    db.commit()

    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr(
        "app.services.beatport.search_beatport_tracks",
        _Spy([_beatport_hit("Strobe", "deadmau5")]),
    )
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", _Spy([]))
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline._get_isrc_from_spotify",
        lambda url: "USABC1234567",
    )

    feats = SoundchartsAudioFeatures(
        isrc="USABC1234567",
        soundcharts_uuid="uuid-1234",
        energy=8,
        danceability=0.7,
        valence=0.6,
        acousticness=0.1,
        instrumentalness=0.0,
        speechiness=0.05,
        liveness=0.2,
        loudness_db=-5.0,
        tempo_bpm=128.0,
        key=5,
        mode=0,
        time_signature=4,
        explicit=False,
        duration_sec=320,
        genres=("progressive house",),
    )
    feature_spy = _Spy(feats)
    monkeypatch.setattr("app.services.soundcharts.get_song_features_by_isrc", feature_spy)
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline.get_settings",
        lambda: _settings_stub(enabled=True),
    )

    enrich_request_metadata(db, request.id)

    assert feature_spy.calls == 1
    sig = dedupe_signature("deadmau5", "Strobe")
    track = get_track(db, signature=sig)
    assert track is not None
    assert track.energy == 8
    assert track.provenance["energy"]["source"] == "soundcharts"
    # Soundcharts must NOT clobber the cascade's bpm/key/genre.
    assert track.provenance["bpm"]["source"] == "beatport"
    # ISRC + uuid captured into identity.
    assert track.isrc == "USABC1234567"
    assert track.soundcharts_uuid == "uuid-1234"
