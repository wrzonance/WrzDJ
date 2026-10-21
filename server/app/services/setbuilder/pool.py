"""WrzDJSet pool service (issue #388).

The pool is a set's candidate-track surface. Tracks flow in from five
import flows (event requests, Tidal playlist, Beatport playlist, public
playlist URL, manual single-track search); every track is tagged with the
SetPoolSource it came through so removal flows can operate per-source.

Dedupe on import: exact ISRC match against the pool first, then a
normalized artist+title signature (via services/track_normalizer). The
first import wins — the original source tag is preserved.
"""

import dataclasses
import logging
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.core.track_ids import valid_isrc
from app.models.set import Set
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User
from app.services.setbuilder.constants import AVG_TRACK_LENGTH_SEC
from app.services.setbuilder.pool_sources import (
    _apply_candidate_to_pool_track,
    _candidate_from_pool_track,
)
from app.services.setbuilder.pool_sources import (
    candidate_from_manual as candidate_from_manual,
)
from app.services.setbuilder.pool_sources import (
    candidates_from_beatport as candidates_from_beatport,
)
from app.services.setbuilder.pool_sources import (
    candidates_from_event as candidates_from_event,
)
from app.services.setbuilder.pool_sources import (
    candidates_from_public_url as candidates_from_public_url,
)
from app.services.setbuilder.pool_sources import (
    candidates_from_tidal as candidates_from_tidal,
)
from app.services.setbuilder.pool_sources import (
    preview_public_playlist as preview_public_playlist,
)
from app.services.setbuilder.pool_types import (
    PoolCandidate,
    camelot_code,
)
from app.services.setbuilder.pool_types import (
    PoolImportError as PoolImportError,
)
from app.services.tracks.enrichment import enrich_track
from app.services.tracks.identity import dedupe_signature
from app.services.tracks.provenance import is_cache_authoritative
from app.services.tracks.store import TrackIdentity, get_track, upsert_track

logger = logging.getLogger(__name__)

POOL_ENRICH_PENDING = "pending"
POOL_ENRICHED = "enriched"
POOL_ENRICH_FAILED = "failed"


def _normalize_isrc(isrc: str | None) -> str | None:
    if not isrc:
        return None
    cleaned = isrc.strip().upper().replace("-", "")
    return cleaned or None


# ---------------------------------------------------------------------------
# Pool reads


def get_pool(db: Session, set_id: int) -> tuple[list[SetPoolSource], list[SetPoolTrack]]:
    """All sources + tracks for a set, in stable insertion order."""
    sources = (
        db.query(SetPoolSource)
        .filter(SetPoolSource.set_id == set_id)
        .order_by(SetPoolSource.id)
        .all()
    )
    tracks = (
        db.query(SetPoolTrack).filter(SetPoolTrack.set_id == set_id).order_by(SetPoolTrack.id).all()
    )
    return sources, tracks


def pool_runtime_sec(db: Session, set_id: int) -> int:
    """Total candidate runtime of a set's pool, in seconds (#538).

    Σ of each pool track's ``duration_sec`` with the pass-1 average fallback for
    missing/non-positive durations, so the figure matches what the deterministic
    builder budgets against. Surfaced before generation so the build dialog can
    state "Pool: N tracks (~M min)" against the target. An empty pool is 0.
    """
    durations = db.query(SetPoolTrack.duration_sec).filter(SetPoolTrack.set_id == set_id).all()
    return sum(dur if dur and dur > 0 else AVG_TRACK_LENGTH_SEC for (dur,) in durations)


def get_owned_source(db: Session, set_obj: Set, source_id: int) -> SetPoolSource | None:
    """Fetch a source scoped to the set. None if missing or from another set."""
    return (
        db.query(SetPoolSource)
        .filter(SetPoolSource.id == source_id, SetPoolSource.set_id == set_obj.id)
        .one_or_none()
    )


# ---------------------------------------------------------------------------
# Sources + import


def get_or_create_source(
    db: Session,
    set_obj: Set,
    *,
    kind: str,
    external_ref: str | None,
    label: str,
    meta: str | None = None,
) -> SetPoolSource:
    """Find-or-create the source row for (set, kind, external_ref).

    Re-importing the same playlist/event reuses the existing row (label and
    meta are refreshed) so counts stay consistent and no duplicate source
    rows ever appear in the accordion.
    """
    existing = (
        db.query(SetPoolSource)
        .filter(
            SetPoolSource.set_id == set_obj.id,
            SetPoolSource.kind == kind,
            SetPoolSource.external_ref == external_ref,
        )
        .first()
    )
    if existing is not None:
        existing.label = label
        if meta is not None:
            existing.meta = meta
        db.flush()
        return existing
    source = SetPoolSource(
        set_id=set_obj.id, kind=kind, external_ref=external_ref, label=label, meta=meta
    )
    db.add(source)
    db.flush()
    return source


def import_candidates(
    db: Session,
    set_obj: Set,
    source: SetPoolSource,
    candidates: Iterable[PoolCandidate],
    *,
    commit: bool = True,
) -> tuple[int, int]:
    """Insert candidates into the pool, deduping against existing tracks.

    Returns (added, deduped). Dedupe order: ISRC exact match, then
    normalized artist+title signature. First import wins — existing rows
    keep their original source tag.
    """
    existing = db.query(SetPoolTrack.dedupe_sig, SetPoolTrack.isrc).filter(
        SetPoolTrack.set_id == set_obj.id
    )
    seen_sigs: set[str] = set()
    seen_isrcs: set[str] = set()
    for sig, isrc in existing:
        seen_sigs.add(sig)
        norm = _normalize_isrc(isrc)
        if norm:
            seen_isrcs.add(norm)

    added = 0
    deduped = 0
    for c in candidates:
        title = (c.title or "").strip()
        artist = (c.artist or "").strip()
        if not title or not artist:
            continue
        sig = dedupe_signature(artist, title)
        isrc = _normalize_isrc(c.isrc)
        if sig in seen_sigs or (isrc and isrc in seen_isrcs):
            deduped += 1
            continue
        db.add(
            SetPoolTrack(
                set_id=set_obj.id,
                source_id=source.id,
                track_id=c.track_id,
                title=title[:255],
                artist=artist[:255],
                album=c.album,
                genre=c.genre,
                bpm=c.bpm,
                key=c.key,
                camelot=camelot_code(c.key),
                energy=c.energy,
                isrc=isrc,
                duration_sec=c.duration_sec,
                artwork_url=c.artwork_url,
                dedupe_sig=sig,
                enrichment_status=POOL_ENRICH_PENDING if _has_provider_gap(c) else POOL_ENRICHED,
            )
        )
        seen_sigs.add(sig)
        if isrc:
            seen_isrcs.add(isrc)
        added += 1

    if commit:
        db.commit()
    else:
        db.flush()
    return added, deduped


# ---------------------------------------------------------------------------
# Master tracks store resolution (#542)
#
# Every import flow runs `hydrate_candidates_from_store` BEFORE `import_candidates`
# so each candidate is enriched once and reused across sets/events via the global
# `tracks` store — the pool-side mirror of the request-side cache-aside (#541).
# `import_candidates` stays a pure dedupe-insert.

# Pool→builder contract fields mapped to (PoolCandidate attr, store attr). `key`
# resolves to the store's Camelot `musical_key`; the rest are 1:1. These are the
# fields hydrated DOWN from a store row onto a candidate (per-field, #554 FIX 3).
# Energy may be hydrated from an authoritative row but is DELIBERATELY excluded
# from the provider-enrich gate (`_has_provider_gap`): it comes only from
# Soundcharts/Lexicon (dark, #543/#544), so gating enrich on it would re-hit
# Beatport/Tidal on every import. Energy completeness is reported separately by
# `pool_coverage` for the build gate.
_CONTRACT_FIELDS: tuple[tuple[str, str], ...] = (
    ("bpm", "bpm"),
    ("key", "musical_key"),
    ("genre", "genre"),
    ("duration_sec", "duration_sec"),
    ("energy", "energy"),
)


def hydrate_candidates_from_store(
    db: Session,
    candidates: Iterable[PoolCandidate],
    *,
    user: User | None = None,
    commit: bool = True,
    enrich_missing: bool = True,
) -> list[PoolCandidate]:
    """Resolve each candidate to the master `tracks` store and fill its gaps.

    Per candidate (immutably — a NEW PoolCandidate is returned, never mutated):
      1. Resolve the store row by ISRC → signature.
      2. Trusted+complete row → hydrate the candidate's missing fields from it
         (ZERO API calls — the dedupe win).
      3. Store miss but the candidate already carries fields → upsert to POPULATE
         the store from the candidate (ZERO API calls).
      4. Genuine gaps AND a connected `user` → run the provider cascade once
         (`enrich_track`), write the result back to the store, then hydrate.
      5. Gaps with no connected `user` → return the candidate unchanged.

    ``commit`` follows ``import_candidates``: the REST import flows commit the
    store write durably (commit-first, so it never poisons the import); the agent
    import tools pass ``commit=False`` so the store write rides the single
    agent-turn transaction and rolls back with it (a dropped cache row is
    harmless and recomputes next import).

    Per-candidate failures are isolated and logged (the import must not abort
    over a best-effort store write); the candidate falls through unhydrated.
    """
    # REST path: the caller has just flushed (not committed) its SetPoolSource row
    # via get_or_create_source. A later per-candidate ``db.rollback()`` (commit=True
    # recovery below) would discard that uncommitted source, leaving
    # import_candidates to insert pool tracks against a dead source.id. Commit ONCE
    # up front so the source is durable; per-candidate rollbacks can then only ever
    # throw away in-flight store-write state, never the source (#554 FIX 1). The
    # agent path (commit=False) owns its single transaction and must NOT commit here.
    if commit:
        db.commit()
    resolved: list[PoolCandidate] = []
    for candidate in candidates:
        try:
            resolved.append(
                _hydrate_one(db, candidate, user, commit=commit, enrich_missing=enrich_missing)
            )
        except Exception as exc:
            # commit=False (agent turn): the session may be poisoned and the turn
            # owns the transaction — re-raise so the turn rolls back atomically
            # rather than continuing on a broken session. commit=True (REST): each
            # candidate is independent and no pool rows are committed yet, so we
            # recover the session and import this one unhydrated.
            if not commit:
                raise
            logger.warning(
                "Pool store hydration failed for '%s' by '%s' (%s); importing as-is.",
                candidate.title,
                candidate.artist,
                type(exc).__name__,
            )
            db.rollback()
            resolved.append(candidate)
    return resolved


def _hydrate_one(
    db: Session,
    candidate: PoolCandidate,
    user: User | None,
    *,
    commit: bool,
    enrich_missing: bool = True,
) -> PoolCandidate:
    """Resolve one candidate against the store and return a gap-filled copy.

    Per-field, not all-or-nothing (#554 FIX 3): each missing candidate field is
    filled from the row when the row's value is present AND authoritative — so a
    PARTIALLY-cached row still contributes (a provider-less DJ benefits from
    whatever the store already holds). Only AFTER that do remaining gaps decide
    populate-vs-enrich-vs-leave, and the store is populated with the candidate's
    OWN brought fields only — never the values just read from the row (which would
    be churn / a provenance downgrade)."""
    title = (candidate.title or "").strip()
    artist = (candidate.artist or "").strip()
    if not title or not artist:
        return candidate
    isrc = valid_isrc(candidate.isrc)
    sig = dedupe_signature(artist, title)

    row = get_track(db, isrc=isrc, signature=sig)
    hydrated_fields: set[str] = set()
    # get_track is ISRC-first then SIGNATURE-fallback, so a candidate with a valid
    # ISRC not in the store can match a DIFFERENT recording's row (same normalized
    # artist/title, different ISRC). Hydrating would copy the wrong recording's
    # fields onto this candidate. Only hydrate when ISRC-compatible — mirrors the
    # request-side guard in sync/enrichment_pipeline. An ISRC-less row (or an
    # ISRC-less candidate) is a compatible signature hit and still hydrates; on a
    # genuine conflict we skip hydration and let enrichment fill the candidate
    # (upsert_track separately refuses the conflicting write, #552/#554 FIX 6).
    isrc_compatible = isrc is None or row is None or row.isrc in (None, isrc)
    if row is not None and isrc_compatible:
        candidate, hydrated_fields = _hydrate_authoritative_fields(candidate, row)

    # Populate the store from the candidate's OWN provider-grade fields that the
    # store still lacks — excluding anything we just hydrated FROM the row.
    if _candidate_has_writable_fields(candidate, exclude=hydrated_fields):
        _write_candidate_to_store(
            db,
            candidate,
            title=title,
            artist=artist,
            sig=sig,
            isrc=isrc,
            commit=commit,
            exclude=hydrated_fields,
        )

    # Genuine remaining gaps in the provider-fillable fields: only a connected DJ
    # can run the cascade. Energy stays out of this gate by design.
    if enrich_missing and _has_provider_gap(candidate) and user is not None:
        return _enrich_and_writeback(
            db, candidate, user, title=title, artist=artist, sig=sig, isrc=isrc, commit=commit
        )
    return candidate


def _hydrate_authoritative_fields(candidate: PoolCandidate, row) -> tuple[PoolCandidate, set[str]]:
    """Fill each MISSING candidate field from the row when the row's value is
    present AND from an authoritative source (50+ precedence). Per-field — a row
    that is only partially trusted still contributes its trusted fields.

    Returns the (possibly new) candidate plus the set of candidate-attr names that
    were hydrated FROM the row, so the caller never writes those back to the store.
    Existing candidate values always win (an import that carries data keeps it).
    ``key`` takes the row's Camelot ``musical_key``/``camelot`` so
    ``import_candidates`` derives the pool ``camelot`` from it. Energy may be
    copied here when authoritative, even though it is excluded from the provider
    short-circuit gate."""
    prov = row.provenance or {}
    updates: dict[str, object] = {}
    hydrated: set[str] = set()
    for cand_attr, store_attr in _CONTRACT_FIELDS:
        if getattr(candidate, cand_attr) is not None:
            continue
        row_value = (
            (row.camelot or row.musical_key)
            if store_attr == "musical_key"
            else getattr(row, store_attr)
        )
        if row_value is None:
            continue
        if not is_cache_authoritative(prov.get(store_attr, {}).get("source", "")):
            continue
        updates[cand_attr] = row_value
        hydrated.add(cand_attr)
    if not updates:
        return candidate, hydrated
    return dataclasses.replace(candidate, **updates), hydrated


def _contract_gap(*, bpm: object, key: object, genre: object, duration_sec: object) -> bool:
    """The single provider-contract gap rule (bpm/key/genre/duration all present).
    Energy is excluded (it comes only from Soundcharts/Lexicon, dark per #543/#544).
    The 064 migration backfill mirrors this in SQL."""
    return bpm is None or not key or not genre or duration_sec is None


def _has_provider_gap(candidate: PoolCandidate) -> bool:
    """True if any provider-fillable field is still missing — the trigger for
    running the enrich cascade."""
    return _contract_gap(
        bpm=candidate.bpm,
        key=candidate.key,
        genre=candidate.genre,
        duration_sec=candidate.duration_sec,
    )


def terminal_enrichment_status(
    *, bpm: object, key: object, genre: object, duration_sec: object
) -> str:
    """Assign a terminal status from a track's contract fields, for paths that
    set status without a background worker to run (snapshot restore; the 064
    backfill mirrors this in SQL). Enriched iff the full contract is present,
    else failed — never "pending", which would report in_progress with nothing
    to clear it."""
    return (
        POOL_ENRICH_FAILED
        if _contract_gap(bpm=bpm, key=key, genre=genre, duration_sec=duration_sec)
        else POOL_ENRICHED
    )


def _candidate_has_writable_fields(candidate: PoolCandidate, *, exclude: set[str]) -> bool:
    """True if the candidate carries at least one contract field (bpm/key/genre/
    duration) worth persisting to the store that was NOT just hydrated from the row.

    ``exclude`` is the set of candidate-attr names filled FROM the row this pass —
    those must not be written back (no churn, no provenance downgrade, #554 FIX 3).
    Must list every field ``_write_candidate_to_store`` actually persists: duration
    is a required pool→builder contract field it writes, so omitting it here skipped
    the store write for a duration-only candidate (e.g. a Spotify/public-URL import
    that carries duration but no bpm/key/genre) and the duration never cached
    (#554 FIX 8). Energy is intentionally NOT a trigger on its own (it never gates a
    build/enrich), but it still rides along when another field triggers the write."""
    return any(
        (
            candidate.bpm is not None and "bpm" not in exclude,
            bool(candidate.key) and "key" not in exclude,
            bool(candidate.genre) and "genre" not in exclude,
            candidate.duration_sec is not None and "duration_sec" not in exclude,
        )
    )


def _candidate_source(candidate: PoolCandidate) -> str:
    """Resolve the store source name a candidate's metadata should be written under.

    Authority comes ONLY from a server-trusted namespaced ``track_id`` prefix that
    the connected-account playlist builders mint (``beatport:<id>`` / ``tidal:<id>``
    — the DJ's own OAuth'd fetch, so the provenance is real). Everything else —
    Spotify (not a bpm/key authority), event requests, and manual SEARCH PICKS —
    attributes ``legacy`` (lowest precedence) and never masquerades as a provider.

    Manual picks are deliberately ``legacy`` even when the client asserts a
    provider: that assertion (``PoolImportManualIn.source_service``) is
    CLIENT-SUPPLIED and unverifiable server-side (the unified search result has no
    server-side provider id — the gap that makes verification impossible). Trusting
    it would let any authenticated DJ POST fabricated bpm/key/genre tagged
    "beatport" and POISON the shared, multi-tenant tracks store that other DJs
    hydrate from. A ``legacy`` row self-heals: the next connected-DJ import runs
    ``enrich_track`` SERVER-SIDE and upgrades it to real beatport/tidal precedence,
    so the precedence guard cleanly overrides it. The one-time re-enrichment cost is
    consciously accepted; security over the dedupe optimization (#554 P1)."""
    track_id = candidate.track_id or ""
    prefix = track_id.split(":", 1)[0] if ":" in track_id else ""
    if prefix in ("beatport", "tidal"):
        return prefix
    return "legacy"


def _write_candidate_to_store(
    db: Session,
    candidate: PoolCandidate,
    *,
    title: str,
    artist: str,
    sig: str,
    isrc: str | None,
    commit: bool,
    exclude: set[str],
) -> None:
    """Upsert the candidate's OWN carried fields into the store (commit-first when
    ``commit``).

    ``exclude`` holds candidate-attr names that were hydrated FROM the row this
    pass — they are skipped so a value just read from the store is never written
    back (#554 FIX 3). Commits any pending work FIRST so a store-write failure
    can't poison an outer transaction (mirrors the request-side
    ``_safe_upsert_track``); the store is strictly additive."""
    source = _candidate_source(candidate)
    values: dict[str, object] = {}
    if candidate.bpm is not None and "bpm" not in exclude:
        values["bpm"] = float(candidate.bpm)
    if "key" not in exclude:
        key_camelot = camelot_code(candidate.key)
        if key_camelot:
            values["musical_key"] = key_camelot
    if candidate.genre and "genre" not in exclude:
        values["genre"] = candidate.genre
    if candidate.duration_sec is not None and "duration_sec" not in exclude:
        values["duration_sec"] = candidate.duration_sec
    if candidate.energy is not None and "energy" not in exclude:
        values["energy"] = candidate.energy
    if not values:
        return
    sources = {field: source for field in values}
    _safe_upsert(
        db,
        title=title,
        artist=artist,
        sig=sig,
        isrc=isrc,
        values=values,
        sources=sources,
        commit=commit,
    )


def _enrich_and_writeback(
    db: Session,
    candidate: PoolCandidate,
    user: User,
    *,
    title: str,
    artist: str,
    sig: str,
    isrc: str | None,
    commit: bool,
) -> PoolCandidate:
    """Run the provider cascade once, write the result back, and hydrate.

    `enrich_track` (Beatport→Tidal) is the same gap-fill the recommendation
    surface uses; its result is upserted to the store at provider precedence so
    the next import of this recording is served from cache. The candidate's
    validated ISRC keys the store row so a later by-ISRC lookup hits it — e.g. a
    Spotify/public-URL candidate that carries an ISRC but no bpm/key/genre (#554
    FIX 2; consistent with #552 storing the submitted ISRC)."""
    profile = enrich_track(db, user, title, artist)
    values: dict[str, object] = {}
    if profile.bpm is not None:
        values["bpm"] = float(profile.bpm)
    key_camelot = camelot_code(profile.key)
    if key_camelot:
        values["musical_key"] = key_camelot
    if profile.genre:
        values["genre"] = profile.genre
    if profile.duration_seconds is not None:
        values["duration_sec"] = profile.duration_seconds
    if not values:
        return candidate
    source = profile.source if profile.source in ("beatport", "tidal") else "legacy"
    sources = {field: source for field in values}
    _safe_upsert(
        db,
        title=title,
        artist=artist,
        sig=sig,
        isrc=isrc,
        values=values,
        sources=sources,
        commit=commit,
    )
    # Fill the candidate from its OWN freshly-enriched values (gap-fill, not
    # authority-gated): this is the data we just resolved for this candidate, so it
    # flows back regardless of the store row's trust tier.
    return _fill_missing(candidate, values)


def _fill_missing(candidate: PoolCandidate, values: dict[str, object]) -> PoolCandidate:
    """Return a copy of the candidate with each missing contract field filled from
    a store ``values`` payload (keyed by store-attr). ``musical_key`` maps to the
    candidate's ``key``. Existing candidate values are preserved."""
    store_to_cand = {store_attr: cand_attr for cand_attr, store_attr in _CONTRACT_FIELDS}
    updates = {
        store_to_cand[store_attr]: value
        for store_attr, value in values.items()
        if store_attr in store_to_cand and getattr(candidate, store_to_cand[store_attr]) is None
    }
    return dataclasses.replace(candidate, **updates) if updates else candidate


def _safe_upsert(
    db: Session,
    *,
    title: str,
    artist: str,
    sig: str,
    isrc: str | None,
    values: dict[str, object],
    sources: dict[str, str],
    commit: bool,
) -> None:
    """Store upsert with the import's commit discipline.

    REST path (``commit=True``): commit-first — durably flush outer work, then
    write the store on top, rolling back only the store write on failure (never
    the import). Agent path (``commit=False``): just flush, so the store write
    rides the single agent-turn transaction (and rolls back with it on undo)."""
    if not commit:
        upsert_track(
            db,
            identity=TrackIdentity(title=title, artist=artist, signature=sig, isrc=isrc),
            values=values,
            sources=sources,
            fetched_at=utcnow(),
        )
        return
    db.commit()
    try:
        upsert_track(
            db,
            identity=TrackIdentity(title=title, artist=artist, signature=sig, isrc=isrc),
            values=values,
            sources=sources,
            fetched_at=utcnow(),
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning(
            "Pool store upsert failed for '%s' by '%s' (%s).", title, artist, type(exc).__name__
        )


# ---------------------------------------------------------------------------
# Background enrichment


def pending_enrichment_track_ids(
    db: Session, set_id: int, *, source_id: int | None = None
) -> list[int]:
    """Pool track IDs still awaiting provider enrichment."""
    query = db.query(SetPoolTrack.id).filter(
        SetPoolTrack.set_id == set_id,
        SetPoolTrack.enrichment_status == POOL_ENRICH_PENDING,
    )
    if source_id is not None:
        query = query.filter(SetPoolTrack.source_id == source_id)
    return [row_id for (row_id,) in query.order_by(SetPoolTrack.id).all()]


def enrich_pool_tracks(
    set_id: int, track_ids: list[int], *, max_workers: int | None = None
) -> None:
    """Background pool enrichment entrypoint.

    The scheduled task receives only scalar IDs. Each worker opens its own
    SessionLocal so external provider calls never pin the request-scoped session
    and SQLAlchemy sessions are not shared across threads.
    """
    unique_ids = list(dict.fromkeys(track_ids))
    if not unique_ids:
        return
    if max_workers is None:
        from app.core.config import get_settings

        max_workers = get_settings().pool_enrich_concurrency
    max_workers = max(1, int(max_workers))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(
            executor.map(
                lambda track_id: _enrich_pool_track_with_fresh_session(set_id, track_id),
                unique_ids,
            )
        )


def _enrich_pool_track_with_fresh_session(set_id: int, track_id: int) -> None:
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        _enrich_pool_track(session, set_id, track_id)
    finally:
        session.close()


def _enrich_pool_track(db: Session, set_id: int, track_id: int) -> None:
    track = db.get(SetPoolTrack, track_id)
    if track is None or track.set_id != set_id:
        return
    set_obj = db.get(Set, set_id)
    user = db.get(User, set_obj.owner_id) if set_obj is not None else None
    if user is None:
        return

    candidate = _candidate_from_pool_track(track)
    try:
        if _has_provider_gap(candidate):
            candidate = _enrich_and_writeback(
                db,
                candidate,
                user,
                title=track.title,
                artist=track.artist,
                sig=track.dedupe_sig,
                isrc=valid_isrc(track.isrc),
                commit=True,
            )
        _apply_candidate_to_pool_track(track, candidate)
        # Only "enriched" if providers actually closed the contract gap. A no-op
        # enrichment (no match / owner has no usable connected services) leaves
        # the same gaps, so mark it "failed" (terminal) rather than "enriched" —
        # otherwise the summary reports completion and a pending-only pass skips
        # the row even though bpm/key/genre/duration are still missing.
        track.enrichment_status = (
            POOL_ENRICH_FAILED if _has_provider_gap(candidate) else POOL_ENRICHED
        )
        db.commit()
    except Exception:
        logger.exception(
            "Pool background enrichment failed for set_id=%s track_id=%s", set_id, track_id
        )
        if not db.is_active or db.new or db.dirty or db.deleted:
            db.rollback()
        failed = db.get(SetPoolTrack, track_id)
        if failed is not None and failed.set_id == set_id:
            failed.enrichment_status = POOL_ENRICH_FAILED
            try:
                db.commit()
            except Exception:
                db.rollback()
                logger.exception(
                    "Could not persist pool enrichment failure for set_id=%s track_id=%s",
                    set_id,
                    track_id,
                )


# ---------------------------------------------------------------------------
# Removal flows


def remove_tracks(db: Session, set_obj: Set, track_ids: list[int]) -> int:
    """Delete pool tracks by id, scoped to the set. Returns rows removed."""
    if not track_ids:
        return 0
    removed = (
        db.query(SetPoolTrack)
        .filter(SetPoolTrack.set_id == set_obj.id, SetPoolTrack.id.in_(track_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return removed


def remove_source(db: Session, set_obj: Set, source: SetPoolSource) -> int:
    """Delete a source and exactly its tracks (cascade). Returns track count removed."""
    count = db.query(SetPoolTrack).filter(SetPoolTrack.source_id == source.id).count()
    db.delete(source)
    db.commit()
    return count
