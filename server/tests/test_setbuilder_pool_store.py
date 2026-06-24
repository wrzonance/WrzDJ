"""Pool import resolves & populates the master tracks store (#542).

`hydrate_candidates_from_store` is the cache-aside step every pool-import flow
runs BEFORE `import_candidates`. It mirrors the request-side pipeline (#541):
  * a trusted+complete store row hydrates the candidate's gaps with ZERO API,
  * a candidate that already carries provider fields POPULATES the store (0 API),
  * genuine gaps with a connected DJ run the provider cascade once, then write
    back to the store and hydrate.

Monkeypatch note: `enrich_track` is top-imported into pool.py, so it is patched
on the pool module. The store write goes through `app.services.tracks.store`.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.models.track import Track
from app.models.user import User
from app.services.recommendation.scorer import TrackProfile
from app.services.setbuilder import pool
from app.services.setbuilder.pool import dedupe_signature, hydrate_candidates_from_store
from app.services.tracks.store import TrackIdentity, get_track, upsert_track


@pytest.fixture
def dj_user(db: Session) -> User:
    from app.services.auth import get_password_hash

    user = User(
        username="pool_store_dj",
        password_hash=get_password_hash("testpassword123"),
        beatport_access_token="fake_bp_token",
        tidal_access_token="fake_tidal_token",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _seed_trusted_complete(db: Session, *, title: str, artist: str) -> Track:
    """A store row fully covered by a real (beatport, precedence 50) provider."""
    sig = dedupe_signature(artist, title)
    row = upsert_track(
        db,
        identity=TrackIdentity(title=title, artist=artist, signature=sig),
        values={
            "bpm": 124.0,
            "musical_key": "8A",
            "genre": "House",
            "duration_sec": 200,
            "energy": 6,
        },
        sources={f: "beatport" for f in ("bpm", "musical_key", "genre", "duration_sec", "energy")},
        fetched_at=datetime.now(UTC),
    )
    db.commit()
    return row


class TestHydrateFromStore:
    def test_trusted_complete_row_hydrates_with_zero_api(self, db, dj_user, monkeypatch):
        _seed_trusted_complete(db, title="Strobe", artist="deadmau5")
        called = {"n": 0}

        def _boom(*a, **k):  # pragma: no cover - must never run
            called["n"] += 1
            raise AssertionError("enrich_track must not be called on a store hit")

        monkeypatch.setattr(pool, "enrich_track", _boom)

        candidate = pool.PoolCandidate(title="Strobe", artist="deadmau5")
        out = hydrate_candidates_from_store(db, [candidate], user=dj_user)

        assert called["n"] == 0
        assert len(out) == 1
        assert out[0].bpm == 124.0
        assert out[0].key == "8A"
        assert out[0].genre == "House"
        assert out[0].duration_sec == 200
        assert out[0].energy == 6

    def test_candidate_with_fields_populates_store_with_zero_api(self, db, dj_user, monkeypatch):
        def _boom(*a, **k):  # pragma: no cover
            raise AssertionError("enrich_track must not be called when candidate is complete")

        monkeypatch.setattr(pool, "enrich_track", _boom)

        candidate = pool.PoolCandidate(
            title="Opus",
            artist="Eric Prydz",
            track_id="beatport:111",
            bpm=126.0,
            key="4A",
            genre="Progressive House",
            duration_sec=540,
            isrc="SEUM71200001",
        )
        out = hydrate_candidates_from_store(db, [candidate], user=dj_user)

        # The candidate is returned unchanged (it already carries the fields) ...
        assert out[0].bpm == 126.0
        # ... and the store now has a row populated from it.
        sig = dedupe_signature("Eric Prydz", "Opus")
        row = get_track(db, isrc="SEUM71200001", signature=sig)
        assert row is not None
        assert row.bpm == 126.0
        assert row.genre == "Progressive House"
        assert row.duration_sec == 540

    def test_gap_with_user_enriches_once_and_writes_back(self, db, dj_user, monkeypatch):
        calls = {"n": 0}

        def _fake_enrich(db_, user_, title, artist):
            calls["n"] += 1
            return TrackProfile(
                title=title,
                artist=artist,
                bpm=128.0,
                key="5A",
                genre="Trance",
                duration_seconds=400,
                source="beatport",
            )

        monkeypatch.setattr(pool, "enrich_track", _fake_enrich)

        candidate = pool.PoolCandidate(title="Adagio", artist="Tiesto")
        out = hydrate_candidates_from_store(db, [candidate], user=dj_user)

        assert calls["n"] == 1
        assert out[0].bpm == 128.0
        assert out[0].key == "5A"
        assert out[0].genre == "Trance"
        # The enriched fields are written back to the store for reuse.
        sig = dedupe_signature("Tiesto", "Adagio")
        row = get_track(db, signature=sig)
        assert row is not None
        assert row.bpm == 128.0

    def test_enrich_writeback_persists_the_candidate_isrc(self, db, dj_user, monkeypatch):
        """#554 FIX 2: a Spotify-style candidate (valid ISRC, no bpm/key/genre) takes
        the enrich path; the resulting store row must carry the candidate's ISRC so a
        later by-ISRC lookup hits the cache instead of re-running providers."""

        def _fake_enrich(db_, user_, title, artist):
            return TrackProfile(
                title=title,
                artist=artist,
                bpm=122.0,
                key="3A",
                genre="Deep House",
                duration_seconds=380,
                source="beatport",
            )

        monkeypatch.setattr(pool, "enrich_track", _fake_enrich)

        candidate = pool.PoolCandidate(
            title="Innerbloom", artist="Rufus", track_id="spotify:abc", isrc="AUXXX1700001"
        )
        hydrate_candidates_from_store(db, [candidate], user=dj_user)

        # The store row is keyed by the candidate's ISRC (not signature-only).
        row = get_track(db, isrc="AUXXX1700001")
        assert row is not None
        assert row.isrc == "AUXXX1700001"
        assert row.bpm == 122.0

    def test_partial_trusted_row_hydrates_per_field_even_without_user(self, db, monkeypatch):
        """#554 FIX 3: a store row with authoritative bpm/key/duration but NO genre
        must hydrate those three onto a later candidate (per-field, not all-or-
        nothing) — even with user=None (no providers to fill the gap) — leaving only
        genre missing. Previously the whole row was ignored unless all four were
        present, so a provider-less user got nothing."""

        def _boom(*a, **k):  # pragma: no cover
            raise AssertionError("enrich_track must not run without a connected user")

        monkeypatch.setattr(pool, "enrich_track", _boom)

        sig = dedupe_signature("Pendulum", "Watercolour")
        upsert_track(
            db,
            identity=TrackIdentity(title="Watercolour", artist="Pendulum", signature=sig),
            values={"bpm": 174.0, "musical_key": "11A", "duration_sec": 240},
            sources={f: "beatport" for f in ("bpm", "musical_key", "duration_sec")},
            fetched_at=datetime.now(UTC),
        )
        db.commit()

        candidate = pool.PoolCandidate(title="Watercolour", artist="Pendulum")
        out = hydrate_candidates_from_store(db, [candidate], user=None)

        assert out[0].bpm == 174.0
        assert out[0].key == "11A"
        assert out[0].duration_sec == 240
        assert out[0].genre is None  # the only remaining gap

    def test_partial_row_does_not_rewrite_read_values_to_store(self, db, dj_user, monkeypatch):
        """#554 FIX 3 caveat: fields hydrated FROM the row must not be written BACK
        to the store. A candidate that brought a NEW field (genre) on top of a
        partial trusted row populates only that new field; the row's existing
        beatport-sourced bpm keeps its provenance (no legacy downgrade churn)."""

        def _boom(*a, **k):  # pragma: no cover
            raise AssertionError("a candidate completed by row+own fields must not enrich")

        monkeypatch.setattr(pool, "enrich_track", _boom)

        sig = dedupe_signature("Sub Focus", "Turn Back Time")
        upsert_track(
            db,
            identity=TrackIdentity(title="Turn Back Time", artist="Sub Focus", signature=sig),
            values={"bpm": 170.0, "musical_key": "2A", "duration_sec": 300},
            sources={f: "beatport" for f in ("bpm", "musical_key", "duration_sec")},
            fetched_at=datetime.now(UTC),
        )
        db.commit()

        # Candidate brings genre the store lacks (and re-states the bpm the row has).
        candidate = pool.PoolCandidate(
            title="Turn Back Time", artist="Sub Focus", genre="Drum & Bass", track_id="manual:1"
        )
        out = hydrate_candidates_from_store(db, [candidate], user=dj_user)

        assert out[0].bpm == 170.0  # hydrated from the row
        assert out[0].genre == "Drum & Bass"  # candidate's own
        row = get_track(db, signature=sig)
        # bpm provenance stays beatport (NOT downgraded by a read-back legacy write);
        # genre is newly populated from the candidate.
        assert row.provenance["bpm"]["source"] == "beatport"
        assert row.genre == "Drum & Bass"

    def test_isrc_conflict_skips_signature_fallback_hydration(self, db, monkeypatch):
        """#554 FIX 6: get_track is ISRC-first then signature-fallback, so a candidate
        with a valid ISRC NOT in the store can match a DIFFERENT recording's row (same
        normalized artist/title, different ISRC). Hydrating from it would copy the
        WRONG recording's bpm/key onto this candidate. On ISRC conflict, hydration must
        be SKIPPED (no contamination); enrichment fills the candidate instead."""

        def _boom(*a, **k):  # pragma: no cover
            raise AssertionError("must not enrich without a connected user")

        monkeypatch.setattr(pool, "enrich_track", _boom)

        # A pre-existing row for a DIFFERENT recording with the same signature.
        sig = dedupe_signature("ACDC", "Thunderstruck")
        upsert_track(
            db,
            identity=TrackIdentity(
                title="Thunderstruck",
                artist="ACDC",
                signature=sig,
                isrc="GBXYZ7654321",  # the OTHER recording's ISRC
            ),
            values={"bpm": 134.0, "musical_key": "9A", "genre": "Rock", "duration_sec": 292},
            sources={f: "beatport" for f in ("bpm", "musical_key", "genre", "duration_sec")},
            fetched_at=datetime.now(UTC),
        )
        db.commit()

        # This candidate carries a DIFFERENT valid ISRC (a distinct recording),
        # not in the store; its signature collides with the row above.
        candidate = pool.PoolCandidate(title="Thunderstruck", artist="ACDC", isrc="USABC1234567")
        out = hydrate_candidates_from_store(db, [candidate], user=None)

        # No contamination: the other recording's fields were NOT copied over.
        assert out[0].bpm is None
        assert out[0].key is None
        assert out[0].genre is None

    def test_isrcless_row_still_hydrates_on_signature_hit(self, db, monkeypatch):
        """FIX 6 must not break the normal case: a signature-matched row with NO ISRC
        is a compatible cache hit and still hydrates a candidate that carries an ISRC
        (the ISRC lookup missed, so this can't be a different recording's row)."""

        def _boom(*a, **k):  # pragma: no cover
            raise AssertionError("must not enrich on a compatible signature hit")

        monkeypatch.setattr(pool, "enrich_track", _boom)

        sig = dedupe_signature("Moderat", "A New Error")
        upsert_track(
            db,
            identity=TrackIdentity(title="A New Error", artist="Moderat", signature=sig),
            values={"bpm": 100.0, "musical_key": "6A", "genre": "Electronica", "duration_sec": 400},
            sources={f: "beatport" for f in ("bpm", "musical_key", "genre", "duration_sec")},
            fetched_at=datetime.now(UTC),
        )
        db.commit()

        candidate = pool.PoolCandidate(title="A New Error", artist="Moderat", isrc="DEABC1900001")
        out = hydrate_candidates_from_store(db, [candidate], user=None)

        assert out[0].bpm == 100.0
        assert out[0].key == "6A"
        assert out[0].genre == "Electronica"

    def test_duration_only_candidate_is_cached(self, db, monkeypatch):
        """#554 FIX 8: duration is a required pool→builder contract field that
        _write_candidate_to_store persists, but the write-gate only counted
        bpm/key/genre — so a candidate whose ONLY contributed field is duration_sec
        (e.g. a Spotify/public-URL import) skipped the store write entirely and the
        duration never cached. The store row must carry it for later hydration."""

        def _no_provider(*a, **k):  # user=None below, but guard anyway
            raise AssertionError("no enrich without a user")

        monkeypatch.setattr(pool, "enrich_track", _no_provider)

        candidate = pool.PoolCandidate(
            title="Ambient Piece", artist="Stars of the Lid", duration_sec=480
        )
        hydrate_candidates_from_store(db, [candidate], user=None)

        row = get_track(db, signature=dedupe_signature("Stars of the Lid", "Ambient Piece"))
        assert row is not None
        assert row.duration_sec == 480

    def test_gap_without_user_leaves_candidate_unenriched(self, db, monkeypatch):
        def _boom(*a, **k):  # pragma: no cover
            raise AssertionError("enrich_track must not run without a connected user")

        monkeypatch.setattr(pool, "enrich_track", _boom)

        candidate = pool.PoolCandidate(title="Mystery", artist="Unknown")
        out = hydrate_candidates_from_store(db, [candidate], user=None)

        assert out[0].bpm is None
        assert out[0].genre is None

    def test_second_import_of_same_track_serves_from_store(self, db, dj_user, monkeypatch):
        # First import enriches once; a second import of the same recording must
        # hit the store and make zero further provider calls (the dedupe win).
        calls = {"n": 0}

        def _fake_enrich(db_, user_, title, artist):
            calls["n"] += 1
            return TrackProfile(
                title=title,
                artist=artist,
                bpm=120.0,
                key="1A",
                genre="Tech House",
                duration_seconds=360,
                source="beatport",
            )

        monkeypatch.setattr(pool, "enrich_track", _fake_enrich)

        c1 = pool.PoolCandidate(title="Percolator", artist="Cajmere")
        hydrate_candidates_from_store(db, [c1], user=dj_user)
        assert calls["n"] == 1

        c2 = pool.PoolCandidate(title="Percolator", artist="Cajmere")
        out2 = hydrate_candidates_from_store(db, [c2], user=dj_user)
        assert calls["n"] == 1  # no new provider call
        assert out2[0].bpm == 120.0


class TestManualPickProvenance:
    """#554 review (P1 security): a manual search pick's asserted provider
    ("source_service") is CLIENT-SUPPLIED and unverifiable server-side, so its
    bpm/key/genre must be stored as ``legacy`` (low precedence), NEVER as
    authoritative provider data. Trusting it would let any authenticated DJ poison
    the shared, multi-tenant tracks store with fabricated provider-grade values
    other DJs then hydrate. A ``legacy`` row self-heals: the next connected-DJ
    import runs ``enrich_track`` server-side and upgrades it to real precedence."""

    def _no_enrich(self, monkeypatch):
        def _boom(*a, **k):  # pragma: no cover
            raise AssertionError("enrich_track must not run on a cache hit / complete candidate")

        monkeypatch.setattr(pool, "enrich_track", _boom)

    def test_manual_beatport_pick_stays_legacy(self, db, dj_user, monkeypatch):
        self._no_enrich(monkeypatch)
        # Client claims source_service="beatport", but the server cannot verify it
        # → stored as legacy, never authoritative (anti-poisoning).
        pick = pool.candidate_from_manual(
            title="Strobe",
            artist="deadmau5",
            bpm=128.0,
            key="4A",
            genre="Progressive House",
            duration_sec=600,
            source_service="beatport",
            source_track_id=None,
        )
        assert pick.track_id is None
        hydrate_candidates_from_store(db, [pick], user=dj_user)

        row = get_track(db, signature=dedupe_signature("deadmau5", "Strobe"))
        assert row is not None
        assert row.provenance["bpm"]["source"] == "legacy"
        assert row.provenance["genre"]["source"] == "legacy"

    def test_manual_tidal_pick_stays_legacy(self, db, dj_user, monkeypatch):
        self._no_enrich(monkeypatch)
        pick = pool.candidate_from_manual(
            title="Innerbloom",
            artist="Rufus Du Sol",
            bpm=120.0,
            key="9A",
            genre="Melodic House",
            duration_sec=560,
            source_service="tidal",
            source_track_id=None,
        )
        hydrate_candidates_from_store(db, [pick], user=dj_user)
        row = get_track(db, signature=dedupe_signature("Rufus Du Sol", "Innerbloom"))
        assert row is not None
        assert row.provenance["bpm"]["source"] == "legacy"

    def test_forged_beatport_track_id_cannot_mint_authority(self):
        """#554 FIX 7 (P1): even a crafted POST that supplies BOTH
        source_service="beatport" AND a source_track_id must NOT mint a
        ``beatport:`` prefix — that prefix is the authority signal _candidate_source
        trusts. candidate_from_manual must never forge it from client input."""
        pick = pool.candidate_from_manual(
            title="Pwned",
            artist="Attacker",
            bpm=200.0,
            key="1A",
            genre="Fabricated",
            source_service="beatport",
            source_track_id="123",  # the attack: a fake id to force a beatport: prefix
        )
        assert pick.track_id is None
        assert pool._candidate_source(pick) == "legacy"

    def test_forged_tidal_track_id_cannot_mint_authority(self):
        pick = pool.candidate_from_manual(
            title="Pwned2",
            artist="Attacker",
            bpm=180.0,
            source_service="tidal",
            source_track_id="456",
        )
        assert pick.track_id is None
        assert pool._candidate_source(pick) == "legacy"

    def test_manual_spotify_pick_mints_spotify_prefix_but_stays_legacy(self):
        """Spotify is the one provider the FE sends an id for; it may keep a
        ``spotify:`` reference id, but Spotify is non-authoritative so the source
        still resolves to ``legacy``."""
        pick = pool.candidate_from_manual(
            title="Get Lucky",
            artist="Daft Punk",
            source_service="spotify",
            source_track_id="69kOkLUCkxyZ",
        )
        assert pick.track_id == "spotify:69kOkLUCkxyZ"
        assert pool._candidate_source(pick) == "legacy"

    def test_manual_spotify_pick_stays_legacy(self, db, dj_user, monkeypatch):
        self._no_enrich(monkeypatch)
        pick = pool.candidate_from_manual(
            title="Get Lucky",
            artist="Daft Punk",
            bpm=116.0,
            key="11B",
            genre="Disco",
            duration_sec=369,
            source_service="spotify",
            source_track_id="abc123",
        )
        hydrate_candidates_from_store(db, [pick], user=dj_user)
        row = get_track(db, signature=dedupe_signature("Daft Punk", "Get Lucky"))
        assert row is not None
        assert row.provenance["bpm"]["source"] == "legacy"

    def test_typed_manual_pick_stays_legacy(self, db, dj_user, monkeypatch):
        self._no_enrich(monkeypatch)
        pick = pool.candidate_from_manual(
            title="Untitled Demo",
            artist="Local Artist",
            bpm=125.0,
            key="8A",
            genre="House",
        )
        hydrate_candidates_from_store(db, [pick], user=dj_user)
        row = get_track(db, signature=dedupe_signature("Local Artist", "Untitled Demo"))
        assert row is not None
        assert row.provenance["bpm"]["source"] == "legacy"

    def test_legacy_manual_row_self_heals_via_server_side_enrich(self, db, dj_user, monkeypatch):
        """The accepted trade-off: a manual pick lands as legacy, but a later import
        whose candidate carries NO metadata runs the SERVER-SIDE provider cascade,
        whose authoritative result upgrades the row (precedence guard lets a real
        provider overwrite legacy)."""
        # First: a manual pick seeds the row at legacy.
        pick = pool.candidate_from_manual(
            title="Opus",
            artist="Eric Prydz",
            bpm=99.0,  # deliberately wrong/typed value
            key="1A",
            genre="House",
            source_service="beatport",
        )
        hydrate_candidates_from_store(db, [pick], user=None)
        sig = dedupe_signature("Eric Prydz", "Opus")
        row = get_track(db, signature=sig)
        assert row.provenance["bpm"]["source"] == "legacy"

        # Later: a metadata-less candidate triggers the server-side cascade, whose
        # authoritative beatport result upgrades the row.
        def _fake_enrich(db_, user_, title, artist):
            return TrackProfile(
                title=title,
                artist=artist,
                bpm=126.0,
                key="4A",
                genre="Progressive House",
                duration_seconds=540,
                source="beatport",
            )

        monkeypatch.setattr(pool, "enrich_track", _fake_enrich)
        hydrate_candidates_from_store(
            db, [pool.PoolCandidate(title="Opus", artist="Eric Prydz")], user=dj_user
        )
        db.refresh(row)
        assert row.bpm == 126.0
        assert row.provenance["bpm"]["source"] == "beatport"
