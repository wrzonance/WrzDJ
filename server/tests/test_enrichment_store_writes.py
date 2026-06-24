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


def _make_request(
    db: Session,
    event: Event,
    title: str,
    artist: str,
    dedupe: str,
    *,
    genre: str | None = None,
    bpm: float | None = None,
    musical_key: str | None = None,
    isrc: str | None = None,
) -> Request:
    request = Request(
        event_id=event.id,
        song_title=title,
        artist=artist,
        source="spotify",
        status=RequestStatus.ACCEPTED.value,
        dedupe_key=dedupe,
        genre=genre,
        bpm=bpm,
        musical_key=musical_key,
        isrc=isrc,
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


def test_presupplied_field_reaches_complete_store_row(db: Session, bp_user: User, monkeypatch):
    """REGRESSION (review #541): a request arriving WITH genre pre-set + a Beatport
    hit supplying bpm/key must write a fully complete store row (genre/bpm/key all
    set), with the pre-supplied genre persisted at `legacy` provenance.

    Before the fix, `_apply_enrichment_result` only recorded a field into the store
    payload when the Request was MISSING it, so a pre-supplied genre never reached
    the store — the row stayed genre-less and could never satisfy the cache-aside
    gate. (The legacy genre is then UPGRADED by real providers on the next
    incomplete request — see `test_legacy_row_is_not_an_authoritative_cache_hit`.)
    """
    event = _make_event(db, bp_user, "PRESPA", "PRSPAA")

    title, artist = "Strobe", "deadmau5"
    # Request arrives WITH genre pre-populated (from frontend search metadata).
    request = _make_request(db, event, title, artist, "presupplied_a", genre="Techno")

    genre_spy = _Spy(None)  # MusicBrainz not even consulted (genre present)
    beatport_spy = _Spy([_beatport_hit(title, artist)])  # supplies bpm + key
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", genre_spy)
    monkeypatch.setattr("app.services.beatport.search_beatport_tracks", beatport_spy)
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", _Spy([]))

    enrich_request_metadata(db, request.id)

    # Store row is COMPLETE on the trio — the pre-supplied genre was persisted too.
    sig = dedupe_signature(artist, title)
    track = get_track(db, signature=sig)
    assert track is not None
    assert track.genre == "Techno"
    assert track.bpm == 128.0
    assert track.musical_key == "4A"
    # Pre-supplied genre carries the lowest 'legacy' provenance (no original source);
    # bpm/key carry their real provider source.
    assert track.provenance["genre"]["source"] == "legacy"
    assert track.provenance["bpm"]["source"] == "beatport"


def test_energy_backfills_onto_complete_cached_row_on_repeat(
    db: Session, bp_user: User, monkeypatch
):
    """REGRESSION (review #541): a trio-complete cached row that lacks energy must
    backfill energy from Soundcharts on a repeat request when the gate is on —
    WITHOUT re-running the core Beatport/Tidal/MusicBrainz cascade.

    Before the fix the cache-aside short-circuit returned unconditionally on a
    complete-trio row, so its `cached.energy is None` Soundcharts arm was dead and
    energy could never backfill (contradicting spec §2/§4/§5.4/§7).
    """
    from app.services.soundcharts import SoundchartsAudioFeatures

    event_a = _make_event(db, bp_user, "ENGBKA", "ENGBKW")
    event_b = _make_event(db, bp_user, "ENGBKB", "ENGBKX")
    title, artist = "Strobe", "deadmau5"

    # First request enriches the trio with the gate OFF → row complete, energy None.
    request_a = _make_request(db, event_a, title, artist, "energy_backfill_a")
    request_a.source_url = "https://open.spotify.com/track/abc123"
    db.commit()

    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr(
        "app.services.beatport.search_beatport_tracks",
        _Spy([_beatport_hit(title, artist)]),
    )
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", _Spy([]))
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline._get_isrc_from_spotify",
        lambda url: "USABC1234567",
    )
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline.get_settings",
        lambda: _settings_stub(enabled=False),
    )

    enrich_request_metadata(db, request_a.id)

    sig = dedupe_signature(artist, title)
    track = get_track(db, signature=sig)
    assert track is not None
    assert track.genre and track.bpm and track.musical_key  # complete trio
    assert track.energy is None  # dark gate → no energy yet

    # Second same-song request with the gate ON → backfill ONLY energy, no cascade.
    beatport_spy = _Spy([_beatport_hit(title, artist)])
    tidal_spy = _Spy([])
    genre_spy = _Spy(None)
    monkeypatch.setattr("app.services.beatport.search_beatport_tracks", beatport_spy)
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", tidal_spy)
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", genre_spy)
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline.get_settings",
        lambda: _settings_stub(enabled=True),
    )

    feats = SoundchartsAudioFeatures(
        isrc="USABC1234567",
        soundcharts_uuid="uuid-9999",
        energy=7,
        danceability=0.6,
        valence=0.5,
        acousticness=0.1,
        instrumentalness=0.0,
        speechiness=0.05,
        liveness=0.2,
        loudness_db=-6.0,
        tempo_bpm=128.0,
        key=5,
        mode=0,
        time_signature=4,
        explicit=False,
        duration_sec=300,
        genres=("progressive house",),
    )
    feature_spy = _Spy(feats)
    monkeypatch.setattr("app.services.soundcharts.get_song_features_by_isrc", feature_spy)

    request_b = _make_request(db, event_b, title, artist, "energy_backfill_b")
    request_b.source_url = "https://open.spotify.com/track/abc123"
    db.commit()
    enrich_request_metadata(db, request_b.id)

    # Soundcharts WAS called; core cascade was NOT (dedupe win preserved).
    assert feature_spy.calls == 1
    assert beatport_spy.calls == 0
    assert tidal_spy.calls == 0
    assert genre_spy.calls == 0

    db.refresh(track)
    assert track.energy == 7
    assert track.provenance["energy"]["source"] == "soundcharts"
    assert track.soundcharts_uuid == "uuid-9999"


def test_store_upsert_failure_preserves_request_enrichment(db: Session, bp_user: User, monkeypatch):
    """REGRESSION (review #541): a DB-level upsert_track failure must NOT discard the
    Request's freshly enriched bpm/genre/key.

    Before the fix, a flush-time error left the session in PendingRollback and the
    trailing unconditional db.commit() raised PendingRollbackError, losing the
    Request enrichment. The fix commits the Request enrichment first, then runs the
    store write under its own commit/rollback recovery.
    """
    event = _make_event(db, bp_user, "STFAIL", "STFALW")
    request = _make_request(db, event, "Strobe", "deadmau5", "store_fail")

    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr(
        "app.services.beatport.search_beatport_tracks",
        _Spy([_beatport_hit("Strobe", "deadmau5")]),
    )
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", _Spy([]))

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated store flush failure")

    monkeypatch.setattr("app.services.sync.enrichment_pipeline.upsert_track", _boom)

    # Must not raise despite the store write blowing up.
    enrich_request_metadata(db, request.id)

    db.refresh(request)
    # The Request's own enrichment survived the poisoned store write.
    assert request.bpm == 128.0
    assert request.musical_key == "4A"


def test_complete_submission_seeds_store_without_providers(db: Session, bp_user: User, monkeypatch):
    """REGRESSION (Codex #549 P2): a request arriving with the FULL trio must still
    seed the store (so repeats reuse it) and must NOT call any provider.

    Before the fix, the early `if genre and bpm and key: return` skipped the store
    write entirely, so search-result submissions never populated the store.
    """
    event = _make_event(db, bp_user, "CMPSUB", "CMPSUW")
    request = _make_request(
        db,
        event,
        "Strobe",
        "deadmau5",
        "complete_seed",
        genre="Techno",
        bpm=130.0,
        musical_key="8A",
    )

    beatport_spy = _Spy([_beatport_hit("Strobe", "deadmau5")])
    genre_spy = _Spy("electronic")
    tidal_spy = _Spy([])
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", genre_spy)
    monkeypatch.setattr("app.services.beatport.search_beatport_tracks", beatport_spy)
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", tidal_spy)

    enrich_request_metadata(db, request.id)

    # No provider was consulted for an already-complete request.
    assert beatport_spy.calls == 0
    assert genre_spy.calls == 0
    assert tidal_spy.calls == 0

    # The store was seeded with the Request's trio at `legacy` provenance.
    sig = dedupe_signature("deadmau5", "Strobe")
    track = get_track(db, signature=sig)
    assert track is not None
    assert track.genre == "Techno"
    assert track.bpm == 130.0
    assert track.musical_key == "8A"
    assert track.provenance["genre"]["source"] == "legacy"
    assert track.provenance["bpm"]["source"] == "legacy"


def test_legacy_row_is_not_an_authoritative_cache_hit(db: Session, bp_user: User, monkeypatch):
    """REGRESSION (Codex #549 P2): a complete-but-legacy store row must NOT short-circuit.

    A request that seeded the trio as `legacy` (e.g. a search-result submission)
    leaves a complete row whose values are low-trust. A later incomplete request for
    the same song must fall through to real providers and UPGRADE the row, rather
    than being served the sticky legacy values forever.
    """
    event_a = _make_event(db, bp_user, "LEGAUT", "LEGAUW")
    event_b = _make_event(db, bp_user, "LEGAUB", "LEGAUX")
    title, artist = "Strobe", "deadmau5"

    # Request A arrives complete → seeds a `legacy` trio (genre "Techno").
    request_a = _make_request(
        db,
        event_a,
        title,
        artist,
        "legacy_seed_a",
        genre="Techno",
        bpm=130.0,
        musical_key="8A",
    )
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr("app.services.beatport.search_beatport_tracks", _Spy([]))
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", _Spy([]))
    enrich_request_metadata(db, request_a.id)

    sig = dedupe_signature(artist, title)
    track = get_track(db, signature=sig)
    assert track is not None and track.provenance["genre"]["source"] == "legacy"

    # Request B is incomplete → must NOT short-circuit on the legacy row; real
    # providers run and upgrade the trio to a trusted source.
    request_b = _make_request(db, event_b, title, artist, "legacy_seed_b")
    beatport_spy = _Spy([_beatport_hit(title, artist)])  # genre "Progressive House"
    genre_spy = _Spy(None)
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", genre_spy)
    monkeypatch.setattr("app.services.beatport.search_beatport_tracks", beatport_spy)
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", _Spy([]))

    enrich_request_metadata(db, request_b.id)

    # Providers WERE consulted (no short-circuit on the legacy row)…
    assert beatport_spy.calls == 1
    # …and the store row was upgraded to the real provider source.
    db.refresh(track)
    assert track.genre == "Progressive House"
    assert track.provenance["genre"]["source"] == "beatport"


def test_spotify_isrc_captured_without_tidal_token_for_soundcharts(
    db: Session, bp_user: User, monkeypatch
):
    """REGRESSION (Codex #549 P2): the Spotify ISRC must be captured INDEPENDENTLY of
    a Tidal token so Soundcharts (gate on) can use it.

    Before the fix, `resolved_isrc` was assigned only inside the
    `if user.tidal_access_token` branch, so a DJ without a Tidal token never fed an
    ISRC to the Soundcharts block and energy was silently skipped.
    """
    from app.services.soundcharts import SoundchartsAudioFeatures

    bp_user.tidal_access_token = None  # DJ has Beatport but NO Tidal
    db.commit()

    event = _make_event(db, bp_user, "NOTIDL", "NOTIDW")
    request = _make_request(db, event, "Strobe", "deadmau5", "no_tidal_isrc")
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
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline.get_settings",
        lambda: _settings_stub(enabled=True),
    )
    feats = SoundchartsAudioFeatures(
        isrc="USABC1234567",
        soundcharts_uuid="uuid-nt",
        energy=6,
        danceability=0.5,
        valence=0.5,
        acousticness=0.1,
        instrumentalness=0.0,
        speechiness=0.05,
        liveness=0.2,
        loudness_db=-7.0,
        tempo_bpm=128.0,
        key=5,
        mode=0,
        time_signature=4,
        explicit=False,
        duration_sec=300,
        genres=("progressive house",),
    )
    feature_spy = _Spy(feats)
    monkeypatch.setattr("app.services.soundcharts.get_song_features_by_isrc", feature_spy)

    enrich_request_metadata(db, request.id)

    # ISRC was captured despite the missing Tidal token → Soundcharts ran.
    assert feature_spy.calls == 1
    sig = dedupe_signature("deadmau5", "Strobe")
    track = get_track(db, signature=sig)
    assert track is not None
    assert track.energy == 6
    assert track.isrc == "USABC1234567"


def test_complete_request_backfills_energy_when_gate_on(db: Session, bp_user: User, monkeypatch):
    """REGRESSION (Codex #550 P2): the complete-request seed path must not bypass the
    Soundcharts energy backfill — when the gate is on and the seeded row lacks
    energy, audio features must still be fetched (without the core cascade)."""
    from app.services.soundcharts import SoundchartsAudioFeatures

    event = _make_event(db, bp_user, "CMPENG", "CMPENW")
    request = _make_request(
        db,
        event,
        "Strobe",
        "deadmau5",
        "complete_energy",
        genre="Techno",
        bpm=130.0,
        musical_key="8A",
    )
    request.source_url = "https://open.spotify.com/track/abc123"
    db.commit()

    beatport_spy = _Spy([])
    monkeypatch.setattr("app.services.beatport.search_beatport_tracks", beatport_spy)
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", _Spy([]))
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline._get_isrc_from_spotify", lambda url: "USABC1234567"
    )
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline.get_settings", lambda: _settings_stub(enabled=True)
    )
    feats = SoundchartsAudioFeatures(
        isrc="USABC1234567",
        soundcharts_uuid="u-ce",
        energy=9,
        danceability=0.5,
        valence=0.5,
        acousticness=0.1,
        instrumentalness=0.0,
        speechiness=0.05,
        liveness=0.2,
        loudness_db=-5.0,
        tempo_bpm=130.0,
        key=5,
        mode=0,
        time_signature=4,
        explicit=False,
        duration_sec=300,
        genres=(),
    )
    feature_spy = _Spy(feats)
    monkeypatch.setattr("app.services.soundcharts.get_song_features_by_isrc", feature_spy)

    enrich_request_metadata(db, request.id)

    assert feature_spy.calls == 1  # energy backfilled on the complete path
    assert beatport_spy.calls == 0  # core cascade still skipped
    track = get_track(db, signature=dedupe_signature("deadmau5", "Strobe"))
    assert track is not None
    assert track.energy == 9
    assert track.provenance["energy"]["source"] == "soundcharts"


def test_no_spotify_isrc_fetch_when_no_consumer(db: Session, bp_user: User, monkeypatch):
    """REGRESSION (Codex #550 P2): for a Spotify request with NO Tidal token and the
    Soundcharts gate OFF, nothing consumes an ISRC — so the external Spotify lookup
    must be skipped entirely."""
    bp_user.tidal_access_token = None
    db.commit()

    event = _make_event(db, bp_user, "NOCONS", "NOCONW")
    request = _make_request(db, event, "Strobe", "deadmau5", "no_consumer")
    request.source_url = "https://open.spotify.com/track/abc123"
    db.commit()

    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr(
        "app.services.beatport.search_beatport_tracks", _Spy([_beatport_hit("Strobe", "deadmau5")])
    )
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", _Spy([]))
    isrc_spy = _Spy("USABC1234567")
    monkeypatch.setattr("app.services.sync.enrichment_pipeline._get_isrc_from_spotify", isrc_spy)
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline.get_settings", lambda: _settings_stub(enabled=False)
    )

    enrich_request_metadata(db, request.id)

    assert isrc_spy.calls == 0  # no Tidal token + gate off → ISRC has no consumer


def test_complete_request_seed_normalizes_key(db: Session, bp_user: User, monkeypatch):
    """REGRESSION (CodeRabbit #550): a complete request's key is normalized to Camelot
    before seeding, so the store matches what the cascade would have written."""
    event = _make_event(db, bp_user, "SEEDNK", "SEEDNW")
    request = _make_request(
        db,
        event,
        "Strobe",
        "deadmau5",
        "seed_norm_key",
        genre="Techno",
        bpm=130.0,
        musical_key="F Minor",
    )
    monkeypatch.setattr("app.services.beatport.search_beatport_tracks", _Spy([]))
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", _Spy([]))

    enrich_request_metadata(db, request.id)

    track = get_track(db, signature=dedupe_signature("deadmau5", "Strobe"))
    assert track is not None
    assert track.musical_key == "4A"  # "F Minor" normalized to Camelot on seed


def test_unprovenanced_complete_row_is_not_authoritative(db: Session, bp_user: User, monkeypatch):
    """REGRESSION (CodeRabbit #550): a complete row with MISSING provenance must not be
    treated as an authoritative cache hit — real providers must still run to upgrade it."""
    from app.models.track import Track

    title, artist = "Strobe", "deadmau5"
    sig = dedupe_signature(artist, title)
    db.add(
        Track(
            signature=sig,
            title=title,
            artist=artist,
            genre="Old",
            bpm=100.0,
            musical_key="1A",
            provenance={},
        )
    )
    db.commit()

    event = _make_event(db, bp_user, "UNPROV", "UNPRVW")
    request = _make_request(db, event, title, artist, "unprov_req")
    beatport_spy = _Spy([_beatport_hit(title, artist)])
    monkeypatch.setattr("app.services.beatport.search_beatport_tracks", beatport_spy)
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", _Spy([]))

    enrich_request_metadata(db, request.id)

    assert beatport_spy.calls == 1  # missing provenance → not trusted → providers ran
    track = get_track(db, signature=sig)
    assert track.provenance["genre"]["source"] == "beatport"  # upgraded from unprovenanced


def test_cache_hit_applies_bpm_context_correction(db: Session, bp_user: User, monkeypatch):
    """REGRESSION (Codex #550 P2): the cache-hit fast path must context-correct the
    served BPM for THIS event (half/double-time), not commit the canonical store
    value raw — matching the miss path. The store value itself stays canonical."""
    from app.models.track import Track

    title, artist = "Strobe", "deadmau5"
    sig = dedupe_signature(artist, title)
    prov = {
        f: {"source": "beatport", "fetched_at": "2026-06-24T00:00:00"}
        for f in ("genre", "bpm", "musical_key")
    }
    db.add(
        Track(
            signature=sig,
            title=title,
            artist=artist,
            genre="Progressive House",
            bpm=66.0,
            musical_key="4A",
            provenance=prov,
        )
    )
    db.commit()

    event = _make_event(db, bp_user, "BPMCTX", "BPMCTW")
    # >=3 ACCEPTED tracks at ~130 BPM establish the event's tempo context
    # (normalize_bpm_to_context requires at least 3 context values).
    _make_request(db, event, "Ctx1", "A1", "ctx1", bpm=130.0)
    _make_request(db, event, "Ctx2", "A2", "ctx2", bpm=130.0)
    _make_request(db, event, "Ctx3", "A3", "ctx3", bpm=130.0)
    request = _make_request(db, event, title, artist, "bpmctx_req")  # incomplete → cache hit

    beatport_spy = _Spy([_beatport_hit(title, artist)])
    monkeypatch.setattr("app.services.beatport.search_beatport_tracks", beatport_spy)
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", _Spy([]))

    enrich_request_metadata(db, request.id)

    assert beatport_spy.calls == 0  # served from the trusted store row, no providers
    db.refresh(request)
    # 66 BPM doubled to match the ~130 event context (half/double-time correction).
    assert request.bpm == 132.0
    # The canonical store value is unchanged — correction is per-event, request-only.
    assert get_track(db, signature=sig).bpm == 66.0


def test_miss_path_stores_canonical_bpm_not_event_corrected(
    db: Session, bp_user: User, monkeypatch
):
    """REGRESSION (Codex #550 P2): on the miss path the global store keeps the
    CANONICAL provider BPM, never the event-context-corrected value. The Request
    gets the corrected value (for this event); the tracks row keeps the provider
    value so OTHER events re-derive their own per-event correction from it."""
    from app.schemas.beatport import BeatportSearchResult

    event = _make_event(db, bp_user, "CANBPM", "CANBPW")
    # >=3 ACCEPTED tracks at ~130 BPM → a provider 66 BPM double-corrects to 132.
    _make_request(db, event, "C1", "A1", "cbpm1", bpm=130.0)
    _make_request(db, event, "C2", "A2", "cbpm2", bpm=130.0)
    _make_request(db, event, "C3", "A3", "cbpm3", bpm=130.0)
    request = _make_request(db, event, "Strobe", "deadmau5", "canbpm_req")  # incomplete

    hit = BeatportSearchResult(
        track_id="9",
        title="Strobe",
        artist="deadmau5",
        genre="Progressive House",
        bpm=66,
        key="F Minor",
    )
    monkeypatch.setattr("app.services.beatport.search_beatport_tracks", _Spy([hit]))
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", _Spy([]))

    enrich_request_metadata(db, request.id)

    db.refresh(request)
    assert request.bpm == 132.0  # event-corrected on the Request
    track = get_track(db, signature=dedupe_signature("deadmau5", "Strobe"))
    assert track is not None
    assert track.bpm == 66.0  # CANONICAL provider value in the store, NOT 132
    assert track.provenance["bpm"]["source"] == "beatport"


def test_presupplied_bpm_seeded_canonical_not_event_corrected(
    db: Session, bp_user: User, monkeypatch
):
    """REGRESSION (Codex #550 P2): a PRE-SUPPLIED bpm seeded as `legacy` must be the
    CANONICAL value, not the event-corrected one — the store-canonical rule has to
    hold on the legacy-seed path too, not only the provider-resolved path."""
    event = _make_event(db, bp_user, "PSBPM", "PSBPMW")
    _make_request(db, event, "C1", "A1", "psb1", bpm=130.0)
    _make_request(db, event, "C2", "A2", "psb2", bpm=130.0)
    _make_request(db, event, "C3", "A3", "psb3", bpm=130.0)
    # Arrives WITH bpm=66 pre-supplied, missing genre/key → bpm is seeded `legacy`.
    request = _make_request(db, event, "Strobe", "deadmau5", "psbpm_req", bpm=66.0)

    # Beatport supplies genre/key; its bpm is ignored (request already has one).
    monkeypatch.setattr(
        "app.services.beatport.search_beatport_tracks", _Spy([_beatport_hit("Strobe", "deadmau5")])
    )
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", _Spy([]))

    enrich_request_metadata(db, request.id)

    db.refresh(request)
    assert request.bpm == 132.0  # event-corrected on the Request (66 doubled)
    track = get_track(db, signature=dedupe_signature("deadmau5", "Strobe"))
    assert track is not None
    assert track.bpm == 66.0  # canonical pre-supplied value seeded, NOT 132
    assert track.provenance["bpm"]["source"] == "legacy"


def test_isrc_first_cache_hit_across_variant_signature(db: Session, bp_user: User, monkeypatch):
    """ISRC-FIRST cache (#552): an incomplete request whose ISRC matches a trusted
    store row reuses it even when the normalized signature DIFFERS (credit variant)
    — zero provider calls, no re-derivation."""
    from app.models.track import Track

    db.add(
        Track(
            signature="unrelated-credit-variant-sig",
            isrc="USXYZ1234567",
            title="Strobe",
            artist="deadmau5 & Friend",
            genre="Progressive House",
            bpm=128.0,
            musical_key="4A",
            provenance={
                f: {"source": "beatport", "fetched_at": "2026-06-24T00:00:00"}
                for f in ("genre", "bpm", "musical_key")
            },
        )
    )
    db.commit()

    event = _make_event(db, bp_user, "ISRCFC", "ISRCFW")
    # Normalizes to a DIFFERENT signature, but carries the same ISRC.
    request = _make_request(db, event, "Strobe", "deadmau5", "isrc_fc", isrc="USXYZ1234567")
    assert dedupe_signature("deadmau5", "Strobe") != "unrelated-credit-variant-sig"

    beatport_spy = _Spy([_beatport_hit("Strobe", "deadmau5")])
    monkeypatch.setattr("app.services.beatport.search_beatport_tracks", beatport_spy)
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", _Spy([]))

    enrich_request_metadata(db, request.id)

    assert beatport_spy.calls == 0  # ISRC-keyed cache hit → no provider re-derivation
    db.refresh(request)
    assert request.genre == "Progressive House"
    assert request.bpm == 128.0
    assert request.musical_key == "4A"


def test_complete_submission_with_isrc_collapses_no_duplicate(
    db: Session, bp_user: User, monkeypatch
):
    """ISRC-first seed (#552): a COMPLETE submission carrying an ISRC collapses onto
    the existing ISRC row even under a different signature — no duplicate row (the
    edge Codex flagged)."""
    from app.models.track import Track

    db.add(
        Track(
            signature="existing-sig-for-isrc",
            isrc="USABC7654321",
            title="Strobe",
            artist="deadmau5",
            genre="Trance",
            bpm=130.0,
            musical_key="8A",
            provenance={
                f: {"source": "beatport", "fetched_at": "2026-06-24T00:00:00"}
                for f in ("genre", "bpm", "musical_key")
            },
        )
    )
    db.commit()

    event = _make_event(db, bp_user, "ISRCDUP", "ISRCDW")
    # Complete submission, credit-variant signature, SAME ISRC.
    request = _make_request(
        db,
        event,
        "Strobe",
        "deadmau5 & Guest",
        "isrc_dup",
        genre="Techno",
        bpm=132.0,
        musical_key="9A",
        isrc="USABC7654321",
    )
    monkeypatch.setattr("app.services.beatport.search_beatport_tracks", _Spy([]))
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr("app.services.tidal.search_tidal_tracks", _Spy([]))

    enrich_request_metadata(db, request.id)

    rows = db.query(Track).filter(Track.isrc == "USABC7654321").all()
    assert len(rows) == 1, "complete submission with ISRC must collapse onto the existing row"
    assert rows[0].signature == "existing-sig-for-isrc"  # no second signature-only row
