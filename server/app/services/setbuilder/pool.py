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
import hashlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.models.set import Set
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User
from app.services.recommendation.camelot import parse_key
from app.services.recommendation.enrichment import enrich_track
from app.services.track_normalizer import normalize_track, valid_isrc
from app.services.tracks.provenance import is_cache_authoritative
from app.services.tracks.store import TrackIdentity, get_track, upsert_track

logger = logging.getLogger(__name__)


class PoolImportError(Exception):
    """Import failed for a user-presentable reason (message is safe to surface)."""


@dataclass(frozen=True)
class PoolCandidate:
    """A track candidate produced by an import flow, pre-insert."""

    title: str
    artist: str
    track_id: str | None = None
    album: str | None = None
    genre: str | None = None
    bpm: float | None = None
    key: str | None = None
    energy: int | None = None
    isrc: str | None = None
    duration_sec: int | None = None
    artwork_url: str | None = None


def dedupe_signature(artist: str, title: str) -> str:
    """Normalized artist+title hash — the fuzzy fallback dedupe key."""
    n = normalize_track(title, artist)
    normalized = f"{n.artist.lower().strip()}:{n.title.lower().strip()}"
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


def camelot_code(key: str | None) -> str | None:
    """Convert any common key notation to a Camelot code ('8B'), or None."""
    pos = parse_key(key)
    return str(pos) if pos else None


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
            resolved.append(_hydrate_one(db, candidate, user, commit=commit))
        except Exception:
            # commit=False (agent turn): the session may be poisoned and the turn
            # owns the transaction — re-raise so the turn rolls back atomically
            # rather than continuing on a broken session. commit=True (REST): each
            # candidate is independent and no pool rows are committed yet, so we
            # recover the session and import this one unhydrated.
            if not commit:
                raise
            logger.warning(
                "Pool store hydration failed for '%s' by '%s'; importing as-is.",
                candidate.title,
                candidate.artist,
            )
            db.rollback()
            resolved.append(candidate)
    return resolved


def _hydrate_one(
    db: Session, candidate: PoolCandidate, user: User | None, *, commit: bool
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
    if _has_provider_gap(candidate) and user is not None:
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


def _has_provider_gap(candidate: PoolCandidate) -> bool:
    """True if any provider-fillable field (bpm/key/genre/duration) is still
    missing — the trigger for running the enrich cascade. Energy is excluded (it
    comes only from Soundcharts/Lexicon, dark per #543/#544)."""
    return (
        candidate.bpm is None
        or not candidate.key
        or not candidate.genre
        or candidate.duration_sec is None
    )


def _candidate_has_writable_fields(candidate: PoolCandidate, *, exclude: set[str]) -> bool:
    """True if the candidate carries at least one core provider field (bpm/key/
    genre) worth persisting to the store that was NOT just hydrated from the row.

    ``exclude`` is the set of candidate-attr names filled FROM the row this pass —
    those must not be written back (no churn, no provenance downgrade, #554 FIX 3).
    A candidate brings store-worthy data only when one of bpm/key/genre is its OWN
    (e.g. a Beatport/Tidal playlist row, or a new field on top of a partial row)."""
    return any(
        (
            candidate.bpm is not None and "bpm" not in exclude,
            bool(candidate.key) and "key" not in exclude,
            bool(candidate.genre) and "genre" not in exclude,
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
    except Exception:
        db.rollback()
        logger.warning("Pool store upsert failed for '%s' by '%s'.", title, artist)


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


# ---------------------------------------------------------------------------
# Candidate builders (one per import flow)


def candidates_from_event(
    db: Session, user: User, event_id: int
) -> tuple[Event, list[PoolCandidate]] | None:
    """Map a DJ's own event's non-rejected requests to candidates.

    Returns None if the event is missing or not owned by the user (the API
    layer surfaces a 404 to avoid leaking existence).
    """
    event = (
        db.query(Event)
        .filter(Event.id == event_id, Event.created_by_user_id == user.id)
        .one_or_none()
    )
    if event is None:
        return None
    requests = (
        db.query(Request)
        .filter(
            Request.event_id == event.id,
            Request.status != RequestStatus.REJECTED.value,
        )
        .order_by(Request.id)
        .all()
    )
    candidates = [
        PoolCandidate(
            track_id=f"request:{r.id}",
            title=r.song_title,
            artist=r.artist,
            genre=r.genre,
            bpm=r.bpm,
            key=r.musical_key,
        )
        for r in requests
    ]
    return event, candidates


def candidates_from_tidal(db: Session, user: User, playlist_id: str) -> list[PoolCandidate]:
    """Fetch a connected-account Tidal playlist's tracks as candidates.

    Raises tidal.TidalFetchError on fetch failure (caller maps to 502).
    """
    from app.services import tidal

    raw_tracks = tidal.get_playlist_tracks(db, user, playlist_id)
    candidates: list[PoolCandidate] = []
    for raw in raw_tracks:
        r = tidal._track_to_result(raw)
        candidates.append(
            PoolCandidate(
                track_id=f"tidal:{r.track_id}",
                title=f"{r.title} ({r.version})" if r.version else r.title,
                artist=r.artist,
                album=r.album,
                bpm=r.bpm,
                key=r.key,
                isrc=r.isrc,
                duration_sec=r.duration_seconds,
                artwork_url=r.cover_url,
            )
        )
    return candidates


def candidates_from_beatport(db: Session, user: User, playlist_id: str) -> list[PoolCandidate]:
    """Fetch a connected-account Beatport playlist's tracks as candidates."""
    from app.services import beatport

    results = beatport.get_playlist_tracks(db, user, playlist_id)
    candidates: list[PoolCandidate] = []
    for r in results:
        title = r.title
        if r.mix_name and r.mix_name.strip().lower() not in ("original mix", "original"):
            title = f"{r.title} ({r.mix_name})"
        candidates.append(
            PoolCandidate(
                track_id=f"beatport:{r.track_id}",
                title=title,
                artist=r.artist,
                genre=r.genre,
                bpm=float(r.bpm) if r.bpm is not None else None,
                key=r.key,
                duration_sec=r.duration_seconds,
                artwork_url=r.cover_url,
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Public playlist URL (Spotify via client credentials, Tidal via DJ session)

_SPOTIFY_PAGE_SIZE = 100


def preview_public_playlist(db: Session, user: User, provider: str, playlist_id: str) -> dict:
    """Lightweight metadata for the validate→preview card. Never fetches the raw URL."""
    if provider == "spotify":
        return _spotify_playlist_preview(playlist_id)
    if provider == "tidal":
        return _tidal_playlist_preview(db, user, playlist_id)
    raise PoolImportError("This provider isn't supported for public playlist import yet")


def candidates_from_public_url(
    db: Session, user: User, provider: str, playlist_id: str
) -> tuple[str, list[PoolCandidate]]:
    """Fetch all tracks of a public playlist. Returns (playlist_name, candidates)."""
    if provider == "spotify":
        return _spotify_playlist_candidates(playlist_id)
    if provider == "tidal":
        return _tidal_playlist_candidates(db, user, playlist_id)
    raise PoolImportError("This provider isn't supported for public playlist import yet")


def _spotify_client():
    from app.services.spotify import _get_spotify_client

    try:
        return _get_spotify_client()
    except ValueError as e:
        raise PoolImportError("Spotify is not configured on this server") from e


def _spotify_playlist_preview(playlist_id: str) -> dict:
    sp = _spotify_client()
    try:
        data = sp.playlist(playlist_id, fields="name,owner.display_name,tracks.total")
    except Exception as e:
        logger.warning("Spotify playlist preview failed: %s", type(e).__name__)
        raise PoolImportError("Couldn't fetch that Spotify playlist — is it public?") from e
    return {
        "name": data.get("name"),
        "owner": (data.get("owner") or {}).get("display_name"),
        "track_count": (data.get("tracks") or {}).get("total"),
    }


def _spotify_playlist_candidates(playlist_id: str) -> tuple[str, list[PoolCandidate]]:
    sp = _spotify_client()
    preview = _spotify_playlist_preview(playlist_id)
    candidates: list[PoolCandidate] = []
    offset = 0
    try:
        while True:
            page = sp.playlist_items(
                playlist_id,
                limit=_SPOTIFY_PAGE_SIZE,
                offset=offset,
                fields=(
                    "items(track(id,name,duration_ms,external_ids.isrc,"
                    "artists.name,album(name,images))),next"
                ),
                additional_types=("track",),
            )

            items = page.get("items") or []
            for item in items:
                track = item.get("track") or {}
                name = track.get("name")
                artists = ", ".join(
                    a.get("name", "") for a in (track.get("artists") or []) if a.get("name")
                )
                if not name or not artists:
                    continue
                album = track.get("album") or {}
                images = album.get("images") or []
                duration_ms = track.get("duration_ms")
                candidates.append(
                    PoolCandidate(
                        track_id=f"spotify:{track.get('id')}" if track.get("id") else None,
                        title=name,
                        artist=artists,
                        album=album.get("name"),
                        isrc=(track.get("external_ids") or {}).get("isrc"),
                        duration_sec=int(duration_ms / 1000) if duration_ms else None,
                        artwork_url=images[0].get("url") if images else None,
                    )
                )
            if not page.get("next") or not items:
                break
            offset += _SPOTIFY_PAGE_SIZE
    except PoolImportError:
        raise
    except Exception as e:
        logger.warning("Spotify playlist fetch failed: %s", type(e).__name__)
        raise PoolImportError("Couldn't fetch that Spotify playlist — is it public?") from e
    return preview.get("name") or "Spotify playlist", candidates


def _tidal_session_or_error(db: Session, user: User):
    from app.services import tidal

    session = tidal.get_tidal_session(db, user)
    if session is None:
        raise PoolImportError("Connect your Tidal account to import Tidal playlist URLs")
    return session


def _tidal_playlist_preview(db: Session, user: User, playlist_id: str) -> dict:
    session = _tidal_session_or_error(db, user)
    try:
        playlist = session.playlist(playlist_id)
        return {
            "name": playlist.name,
            "owner": None,
            "track_count": getattr(playlist, "num_tracks", None),
        }
    except Exception as e:
        logger.warning("Tidal playlist preview failed: %s", type(e).__name__)
        raise PoolImportError("Couldn't fetch that Tidal playlist — is it public?") from e


def _tidal_playlist_candidates(
    db: Session, user: User, playlist_id: str
) -> tuple[str, list[PoolCandidate]]:
    from app.services import tidal

    preview = _tidal_playlist_preview(db, user, playlist_id)
    try:
        candidates = candidates_from_tidal(db, user, playlist_id)
    except tidal.TidalFetchError as e:
        raise PoolImportError("Couldn't fetch that Tidal playlist — is it public?") from e
    return preview.get("name") or "Tidal playlist", candidates


def candidate_from_manual(
    *,
    title: str,
    artist: str,
    album: str | None = None,
    genre: str | None = None,
    bpm: float | None = None,
    key: str | None = None,
    isrc: str | None = None,
    duration_sec: int | None = None,
    artwork_url: str | None = None,
    source_service: str = "manual",
    source_track_id: str | None = None,
) -> PoolCandidate:
    """Build a candidate from a manual search pick (validated at the API layer).

    ``source_service``/``source_track_id`` are CLIENT input, so this must NEVER mint
    an authoritative ``beatport:``/``tidal:`` track_id from them — that prefix is the
    authority signal ``_candidate_source`` trusts, and forging it would let a crafted
    request write fabricated provider-grade data into the shared, multi-tenant store
    (#554 P1). Authoritative beatport/tidal prefixes come ONLY from the server-side
    playlist builders (``candidates_from_beatport``/``candidates_from_tidal``), which
    mint them from the DJ's OAuth'd server-side fetch — never from this path.

    We keep ONLY a non-authoritative ``spotify:<id>`` reference (Spotify resolves to
    ``legacy`` in ``_candidate_source`` regardless, and it is the one provider the FE
    actually sends an id for). Everything else stays ``track_id=None`` → ``legacy``."""
    track_id = None
    if source_track_id and source_service == "spotify":
        track_id = f"spotify:{source_track_id}"
    return PoolCandidate(
        track_id=track_id,
        title=title,
        artist=artist,
        album=album,
        genre=genre,
        bpm=bpm,
        key=key,
        isrc=isrc,
        duration_sec=duration_sec,
        artwork_url=artwork_url,
    )
