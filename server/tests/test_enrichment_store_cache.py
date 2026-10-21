"""Enrichment-store cache and signature tests."""

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
    _Spy,
)


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
    monkeypatch.setattr("app.services.providers.beatport_catalog.search_beatport_tracks", _Spy([]))
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))

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
    monkeypatch.setattr(
        "app.services.providers.beatport_catalog.search_beatport_tracks", beatport_spy
    )
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))

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
    monkeypatch.setattr(
        "app.services.providers.beatport_catalog.search_beatport_tracks", beatport_spy
    )
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))

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
    monkeypatch.setattr(
        "app.services.providers.beatport_catalog.search_beatport_tracks", _Spy([hit])
    )
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))

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
        "app.services.providers.beatport_catalog.search_beatport_tracks",
        _Spy([_beatport_hit("Strobe", "deadmau5")]),
    )
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))

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
    monkeypatch.setattr(
        "app.services.providers.beatport_catalog.search_beatport_tracks", beatport_spy
    )
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))
    # Pin the Soundcharts gate OFF so the cache-hit energy-backfill arm can't make
    # a real API call if the env happens to enable it (config-coupled flakiness).
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline.get_settings", lambda: _settings_stub(enabled=False)
    )

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
    monkeypatch.setattr("app.services.providers.beatport_catalog.search_beatport_tracks", _Spy([]))
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))
    # Pin the Soundcharts gate OFF so the seeded-row energy-backfill arm can't make
    # a real API call if the env happens to enable it (config-coupled flakiness).
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline.get_settings", lambda: _settings_stub(enabled=False)
    )

    enrich_request_metadata(db, request.id)

    rows = db.query(Track).filter(Track.isrc == "USABC7654321").all()
    assert len(rows) == 1, "complete submission with ISRC must collapse onto the existing row"
    assert rows[0].signature == "existing-sig-for-isrc"  # no second signature-only row


def test_signature_fallback_not_trusted_for_different_isrc(db: Session, bp_user: User, monkeypatch):
    """REGRESSION (Codex #550): a request carrying ISRC_A must NOT short-circuit on a
    signature-matched row whose ISRC differs (a different release of the same
    artist/title). The fast path would otherwise serve the wrong recording's data
    and skip providers — so providers must run instead."""
    from app.models.track import Track

    sig = dedupe_signature("deadmau5", "Strobe")
    db.add(
        Track(
            signature=sig,
            isrc="USREL0000001",  # a DIFFERENT recording's ISRC
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

    event = _make_event(db, bp_user, "ISRCDIF", "ISRCDF")
    request = _make_request(db, event, "Strobe", "deadmau5", "isrc_diff", isrc="USREL0000002")
    beatport_spy = _Spy([_beatport_hit("Strobe", "deadmau5")])
    monkeypatch.setattr(
        "app.services.providers.beatport_catalog.search_beatport_tracks", beatport_spy
    )
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline.get_settings", lambda: _settings_stub(enabled=False)
    )

    enrich_request_metadata(db, request.id)

    assert beatport_spy.calls == 1  # different-ISRC row not trusted → providers ran


def test_isrc_backfilled_onto_isrc_less_cache_hit(db: Session, bp_user: User, monkeypatch):
    """A trusted ISRC-less cached row is still used on the fast path, and the
    request's ISRC is backfilled onto it so future lookups are ISRC-keyed (#552)."""
    from app.models.track import Track

    sig = dedupe_signature("deadmau5", "Strobe")
    db.add(
        Track(
            signature=sig,
            isrc=None,  # no ISRC yet
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

    event = _make_event(db, bp_user, "ISRCBF", "ISRCBW")
    request = _make_request(db, event, "Strobe", "deadmau5", "isrc_bf", isrc="USNEW0000001")
    beatport_spy = _Spy([_beatport_hit("Strobe", "deadmau5")])
    monkeypatch.setattr(
        "app.services.providers.beatport_catalog.search_beatport_tracks", beatport_spy
    )
    monkeypatch.setattr("app.services.sync.enrichment_pipeline.lookup_artist_genre", _Spy(None))
    monkeypatch.setattr("app.services.providers.tidal_search.search_tidal_tracks", _Spy([]))
    monkeypatch.setattr(
        "app.services.sync.enrichment_pipeline.get_settings", lambda: _settings_stub(enabled=False)
    )

    enrich_request_metadata(db, request.id)

    assert beatport_spy.calls == 0  # ISRC-less trusted row → short-circuit, no providers
    track = get_track(db, signature=sig)
    assert track.isrc == "USNEW0000001"  # request's ISRC backfilled onto the row
