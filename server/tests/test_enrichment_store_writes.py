"""Enrichment-store write and provenance tests."""

from sqlalchemy.orm import Session

from app.models.user import User
from app.services.setbuilder.pool import dedupe_signature
from app.services.sync.enrichment_pipeline import enrich_request_metadata
from app.services.tracks.store import get_track
from tests.enrichment_store_test_helpers import (
    _beatport_hit,
    _fixture_bp_user,  # noqa: F401
    _make_event,
    _make_request,
    _settings_stub,
    _spotify_isrc_stub,
    _Spy,
)


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
    monkeypatch.setattr(
        "app.services.providers.beatport_catalog.search_beatport_tracks", beatport_spy
    )
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", tidal_spy)

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
        "app.services.providers.beatport_catalog.search_beatport_tracks",
        _Spy([_beatport_hit("Strobe", "deadmau5")]),  # Beatport provides bpm/key
    )
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))

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
        "app.services.providers.beatport_catalog.search_beatport_tracks",
        _Spy([_beatport_hit("Strobe", "deadmau5")]),
    )
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))

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
        "app.services.providers.beatport_catalog.search_beatport_tracks",
        _Spy([_beatport_hit("Strobe", "deadmau5")]),
    )
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline._get_isrc_from_spotify",
        _spotify_isrc_stub,
    )

    feature_spy = _Spy(None)
    monkeypatch.setattr("app.services.providers.soundcharts.get_song_features_by_isrc", feature_spy)
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
    from app.services.providers.soundcharts import SoundchartsAudioFeatures

    event = _make_event(db, bp_user, "ENGON1", "ENGONW")
    request = _make_request(db, event, "Strobe", "deadmau5", "energy_on")
    request.source_url = "https://open.spotify.com/track/abc123"
    db.commit()

    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr(
        "app.services.providers.beatport_catalog.search_beatport_tracks",
        _Spy([_beatport_hit("Strobe", "deadmau5")]),
    )
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline._get_isrc_from_spotify",
        _spotify_isrc_stub,
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
    monkeypatch.setattr("app.services.providers.soundcharts.get_song_features_by_isrc", feature_spy)
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
    monkeypatch.setattr(
        "app.services.providers.beatport_catalog.search_beatport_tracks", beatport_spy
    )
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))

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
    from app.services.providers.soundcharts import SoundchartsAudioFeatures

    event_a = _make_event(db, bp_user, "ENGBKA", "ENGBKW")
    event_b = _make_event(db, bp_user, "ENGBKB", "ENGBKX")
    title, artist = "Strobe", "deadmau5"

    # First request enriches the trio with the gate OFF → row complete, energy None.
    request_a = _make_request(db, event_a, title, artist, "energy_backfill_a")
    request_a.source_url = "https://open.spotify.com/track/abc123"
    db.commit()

    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr(
        "app.services.providers.beatport_catalog.search_beatport_tracks",
        _Spy([_beatport_hit(title, artist)]),
    )
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline._get_isrc_from_spotify",
        _spotify_isrc_stub,
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
    monkeypatch.setattr(
        "app.services.providers.beatport_catalog.search_beatport_tracks", beatport_spy
    )
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", tidal_spy)
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
    monkeypatch.setattr("app.services.providers.soundcharts.get_song_features_by_isrc", feature_spy)

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
        "app.services.providers.beatport_catalog.search_beatport_tracks",
        _Spy([_beatport_hit("Strobe", "deadmau5")]),
    )
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))

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
    monkeypatch.setattr(
        "app.services.providers.beatport_catalog.search_beatport_tracks", beatport_spy
    )
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", tidal_spy)

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
    monkeypatch.setattr("app.services.providers.beatport_catalog.search_beatport_tracks", _Spy([]))
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))
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
    monkeypatch.setattr(
        "app.services.providers.beatport_catalog.search_beatport_tracks", beatport_spy
    )
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))

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
    from app.services.providers.soundcharts import SoundchartsAudioFeatures

    bp_user.tidal_access_token = None  # DJ has Beatport but NO Tidal
    db.commit()

    event = _make_event(db, bp_user, "NOTIDL", "NOTIDW")
    request = _make_request(db, event, "Strobe", "deadmau5", "no_tidal_isrc")
    request.source_url = "https://open.spotify.com/track/abc123"
    db.commit()

    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr(
        "app.services.providers.beatport_catalog.search_beatport_tracks",
        _Spy([_beatport_hit("Strobe", "deadmau5")]),
    )
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline._get_isrc_from_spotify",
        _spotify_isrc_stub,
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
    monkeypatch.setattr("app.services.providers.soundcharts.get_song_features_by_isrc", feature_spy)

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
    from app.services.providers.soundcharts import SoundchartsAudioFeatures

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
    monkeypatch.setattr(
        "app.services.providers.beatport_catalog.search_beatport_tracks", beatport_spy
    )
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline._get_isrc_from_spotify", _spotify_isrc_stub
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
    monkeypatch.setattr("app.services.providers.soundcharts.get_song_features_by_isrc", feature_spy)

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
        "app.services.providers.beatport_catalog.search_beatport_tracks",
        _Spy([_beatport_hit("Strobe", "deadmau5")]),
    )
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))
    isrc_spy = _Spy("USABC1234567")
    monkeypatch.setattr("app.services.sync.enrichment_pipeline._get_isrc_from_spotify", isrc_spy)
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline.get_settings", lambda: _settings_stub(enabled=False)
    )

    enrich_request_metadata(db, request.id)

    assert isrc_spy.calls == 0  # no Tidal token + gate off → ISRC has no consumer
