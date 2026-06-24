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
