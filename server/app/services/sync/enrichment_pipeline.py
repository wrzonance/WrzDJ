"""Enrichment pipeline — resolves song metadata and writes the master track store.

`enrich_request_metadata` is the single abstracted enrichment entry point for every
request-queue surface (guest submit / collect / kiosk / DJ add / bulk / refresh).
It both fills missing genre/BPM/key on the Request (for the existing UI) AND, since
#541, CACHE-ASIDE dual-writes a master `tracks` row (the single source of truth for
song data) so each unique recording is enriched once and reused across events.

Provider cascade (only for fields still missing):
0. Direct fetch via source_url (Beatport/Tidal URL → exact track)
0b. Spotify URL → ISRC (feeds the optional Tidal exact-match + the Soundcharts lookup)
1. MusicBrainz artist lookup (genre — artist-level, 1 req/sec rate limit)
2. Beatport search (BPM + key, backfill genre if MusicBrainz missed)
3. Tidal search (BPM + key backup when Beatport unavailable)
4. BPM context-correction (per-event; request-only, never written to the store)
5. Soundcharts audio-features (energy/danceability/… — gated, dark by default)

Store write (#541): the master `tracks` row is keyed by ISRC → dedupe_signature,
written with per-field provenance under a precedence ladder; a trusted complete row
short-circuits the whole cascade (the dedupe win). See app/services/tracks/. The
WrzDJSet pool's own master-store write is deferred to #542.
"""

from __future__ import annotations

import logging
import re
import statistics
from collections.abc import Mapping

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.core.track_ids import normalize_isrc
from app.models.request import Request, RequestStatus
from app.services.providers.musicbrainz import lookup_artist_genre
from app.services.request import normalize_key
from app.services.sync.source_resolution import (
    FieldResolution,
    SourceResolutionResult,
    resolve_direct_source_track,
    resolve_spotify_isrc_and_tidal_match,
    track_field_resolutions,
)
from app.services.track_match import find_best_match
from app.services.track_normalizer import (
    is_remix_title,
    normalize_bpm_to_context,
    primary_artist,
)
from app.services.tracks.provenance import is_cache_authoritative
from app.services.tracks.store import TrackIdentity, get_track, upsert_track

logger = logging.getLogger(__name__)

# URL patterns for extracting track IDs from source URLs
_SPOTIFY_URL_RE = re.compile(r"open\.spotify\.com/track/(\w+)")
_BEATPORT_URL_RE = re.compile(r"beatport\.com/track/[^/]+/(\d+)")
_TIDAL_URL_RE = re.compile(r"tidal\.com/(?:browse/)?track/(\d+)")


def _extract_source_track_id(source_url: str | None) -> tuple[str | None, str | None]:
    """Extract (service, track_id) from a source URL.

    Returns:
        ("spotify", "4uLU6hMCjMI75M1A2tKUQC") for Spotify URLs
        ("beatport", "12345") for Beatport URLs
        ("tidal", "67890") for Tidal URLs
        (None, None) for unrecognized URLs
    """
    if not source_url:
        return None, None
    for name, pattern in [
        ("spotify", _SPOTIFY_URL_RE),
        ("beatport", _BEATPORT_URL_RE),
        ("tidal", _TIDAL_URL_RE),
    ]:
        m = pattern.search(source_url)
        if m:
            return name, m.group(1)
    return None, None


def _get_isrc_from_spotify(source_url: str | None, *, request_id: int | None = None) -> str | None:
    """Extract ISRC from a Spotify track URL via the Spotify API.

    ISRC (International Standard Recording Code) uniquely identifies a
    recording across services, enabling deterministic cross-service matching.
    """
    if not source_url:
        return None
    m = _SPOTIFY_URL_RE.search(source_url)
    if not m:
        return None
    try:
        from app.services.providers.spotify import get_spotify_client

        sp = get_spotify_client()
        track = sp.track(m.group(1))
        return track.get("external_ids", {}).get("isrc")
    except Exception as exc:
        logger.warning(
            "Spotify ISRC lookup failed for request %s (%s)",
            request_id if request_id is not None else "unknown",
            type(exc).__name__,
        )
        return None


def _apply_enrichment_result(
    request: Request,
    best,
    *,
    source: str,
    resolved: dict[str, tuple[object, str]],
    with_genre: bool = False,
) -> None:
    """Apply BPM/key (and optionally genre) from a matched result to a request.

    Each field written onto the request is also recorded in ``resolved`` as
    ``field -> (value, source)`` so the master tracks store can be dual-written
    with accurate per-field provenance (#541). ``musical_key`` is normalized to
    its Camelot code so the store matches what the request displays.
    """
    _apply_field_resolutions(
        request,
        resolved,
        track_field_resolutions(request, best, source=source, with_genre=with_genre),
    )


def _apply_field_resolutions(
    request: Request,
    resolved: dict[str, tuple[object, str]],
    fields: Mapping[str, FieldResolution],
) -> None:
    """Apply a prepared field update once and record its provenance."""
    for field, update in fields.items():
        if not getattr(request, field):
            setattr(request, field, update.value)
            resolved[field] = (update.value, update.source)


def _apply_source_resolution(
    request: Request,
    resolved: dict[str, tuple[object, str]],
    result: SourceResolutionResult,
) -> str | None:
    """Apply one source resolver result and return its resolved ISRC."""
    _apply_field_resolutions(request, resolved, result.fields)
    return result.isrc


def _soundcharts_audio_values(feats) -> dict[str, tuple[object, str]]:
    """Map a SoundchartsAudioFeatures result to resolved ``field -> (value, source)``
    entries, dropping None values (a missing feature must not overwrite the store)."""
    audio_fields = {
        "energy": feats.energy,
        "danceability": feats.danceability,
        "valence": feats.valence,
        "acousticness": feats.acousticness,
        "instrumentalness": feats.instrumentalness,
        "speechiness": feats.speechiness,
        "liveness": feats.liveness,
        "loudness_db": feats.loudness_db,
        "time_signature": feats.time_signature,
        "explicit": feats.explicit,
        "duration_sec": feats.duration_sec,
    }
    return {
        field: (value, "soundcharts") for field, value in audio_fields.items() if value is not None
    }


def _backfill_energy_for_cached(db: Session, request: Request, cached, sig: str) -> None:
    """Backfill Soundcharts audio features onto an already-trio-complete store row.

    Reached only from the cache-aside short-circuit when the gate is on and the
    cached row lacks energy (spec §2/§4/§5.4/§7). Resolves the ISRC from the row
    itself (preferred) or the request's Spotify source_url, fetches features, and
    upserts the audio fields onto the existing row WITHOUT running the core
    provider cascade. Best-effort: any failure is isolated and never regresses the
    request commit (the store is strictly additive)."""
    resolved_isrc = cached.isrc or _get_isrc_from_spotify(request.source_url, request_id=request.id)
    if not resolved_isrc:
        return
    try:
        from app.services.providers.soundcharts import get_song_features_by_isrc

        feats = get_song_features_by_isrc(resolved_isrc)
    except Exception as exc:
        logger.warning(
            "Soundcharts energy backfill lookup failed for request %d (%s)",
            request.id,
            type(exc).__name__,
        )
        return
    if not feats:
        return
    resolved = _soundcharts_audio_values(feats)
    if not resolved:
        return
    values = {field: value for field, (value, _src) in resolved.items()}
    sources = {field: src for field, (_value, src) in resolved.items()}
    _safe_upsert_track(
        db,
        identity=TrackIdentity(
            title=request.song_title,
            artist=request.artist,
            signature=sig,
            isrc=resolved_isrc,
            soundcharts_uuid=feats.soundcharts_uuid or None,
        ),
        values=values,
        sources=sources,
        request_id=request.id,
    )


def _safe_upsert_track(
    db: Session,
    *,
    identity: TrackIdentity,
    values: dict[str, object],
    sources: dict[str, str],
    request_id: int,
) -> None:
    """Durably commit the Request's own enrichment, then upsert the store on top.

    A DB-level failure inside ``upsert_track`` (e.g. a flush-time error from a
    constraint or a transient Postgres OperationalError) poisons the session, so a
    naive trailing ``db.commit()`` would raise ``PendingRollbackError`` and discard
    the Request's freshly enriched bpm/genre/key — the opposite of the "store is
    strictly additive, never regress the request commit" guarantee (#541).

    To make that guarantee real we commit the pending Request enrichment FIRST so
    it is durable, then run the store upsert and commit it separately. If the store
    write fails we ``db.rollback()`` to recover the poisoned session — the Request
    is already committed, so nothing it owns is lost; only the best-effort store
    write is dropped (it recomputes on the next request)."""
    db.commit()  # persist the Request's own enrichment before the additive store write
    try:
        upsert_track(
            db,
            identity=identity,
            values=values,
            sources=sources,
            fetched_at=utcnow(),
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning(
            "Track store upsert failed for request %d (%s)", request_id, type(exc).__name__
        )


def _trio_trusted(track) -> bool:
    """True when genre/bpm/musical_key are all present AND each comes from a real
    measured/authoritative provider (the 50+ precedence tier).

    The cache-aside short-circuit may only fire on a TRUSTED row. A row whose trio
    was backfilled/seeded as ``legacy`` — or that carries low-trust (community/llm)
    or missing/unknown provenance — is NOT authoritative: short-circuiting on it
    would copy unupgraded values onto every future request and prevent real
    providers from ever improving them (#541). Falling through instead lets
    Beatport/Tidal/MusicBrainz run and re-upsert at higher precedence, after which
    the row becomes trusted. (``is_cache_authoritative`` treats unknown/missing
    sources as precedence 0, so unprovenanced rows never short-circuit.)"""
    if not (track.genre and track.bpm and track.musical_key):
        return False
    prov = track.provenance or {}
    return all(
        is_cache_authoritative(prov.get(f, {}).get("source", ""))
        for f in ("genre", "bpm", "musical_key")
    )


def _seed_complete_request(db: Session, request: Request, sig: str) -> None:
    """Seed the store from a Request that already carries the full trio.

    Search-result submissions arrive complete and skip the provider cascade
    entirely, so without this they would never populate the store and repeats
    could not reuse it (#541). The Request records no per-field source, so the
    trio is attributed ``legacy`` (lowest precedence); the precedence guard keeps
    it from downgrading a stronger existing row, and a later incomplete request
    upgrades it via real providers (see ``_trio_trusted``). The key is normalized
    to Camelot so the seeded row matches what the cascade would have written.

    Seeds with the Request's ISRC when present (#552): a complete submission that
    carries the search-result ISRC collapses onto the existing ISRC-keyed row even
    when its normalized signature differs (e.g. a collab/credit variant), instead
    of inserting a second signature-only row."""
    values = {
        "genre": request.genre,
        "bpm": request.bpm,
        "musical_key": normalize_key(request.musical_key),
    }
    sources = {field: "legacy" for field in values}
    _safe_upsert_track(
        db,
        identity=TrackIdentity(
            title=request.song_title,
            artist=request.artist,
            signature=sig,
            isrc=request.isrc,
        ),
        values=values,
        sources=sources,
        request_id=request.id,
    )


def _apply_bpm_context_correction(db: Session, request: Request) -> float | None:
    """Half/double-time correct ``request.bpm`` to the event's accepted-track tempo
    context. Mutates ``request.bpm`` and returns the corrected value if it changed,
    else None.

    This is PER-EVENT (the same recording can need different octave correction at
    different events), so it runs on BOTH the provider/miss path and the cache-hit
    fast path — a trusted cached BPM must still be context-corrected for the event
    it's being served into, not committed raw (#541)."""
    if not request.bpm:
        return None
    context_bpms = [
        float(r.bpm)
        for r in db.query(Request)
        .filter(
            Request.event_id == request.event_id,
            Request.id != request.id,
            Request.bpm.isnot(None),
            Request.status.in_(
                [
                    RequestStatus.ACCEPTED.value,
                    RequestStatus.PLAYING.value,
                    RequestStatus.PLAYED.value,
                ]
            ),
        )
        .all()
    ]
    corrected = normalize_bpm_to_context(request.bpm, context_bpms)
    if corrected != request.bpm:
        logger.info(
            "BPM corrected for request %d: %.1f → %.1f (median context: %.1f)",
            request.id,
            request.bpm,
            corrected,
            statistics.median(context_bpms),
        )
        request.bpm = corrected
        return corrected
    return None


def _persist_enrichment_results(
    db: Session,
    request: Request,
    *,
    signature: str,
    resolved: dict[str, tuple[object, str]],
    resolved_isrc: str | None,
    resolved_uuid: str | None,
    canonical_bpm: float | None,
) -> None:
    """Seed pre-supplied values and durably write resolved track metadata."""
    request_id = request.id
    # Seed the request's own pre-supplied/cascade-confirmed core fields into the
    # store payload even when no provider NEWLY resolved them this run (#541). A
    # request can arrive with partial metadata (RequestCreate accepts
    # genre/bpm/musical_key; the frontend submits search-result fields), and
    # `_apply_enrichment_result` only records a field into `resolved` when the
    # Request was MISSING it — so a request that already carried, say, genre would
    # write a genre-less store row, which can never satisfy the cache-aside gate
    # (genre AND bpm AND musical_key) and re-hits every provider forever. Seed each
    # core field the Request holds but `resolved` lacks, attributed to the lowest
    # `legacy` provenance so any real later enrichment cleanly overrides it (the
    # `should_overwrite` precedence guard keeps a stronger existing source).
    for field, value in (
        ("genre", request.genre),
        ("bpm", canonical_bpm),  # pre-correction value — never the event-corrected one
        ("musical_key", request.musical_key),
    ):
        if field not in resolved and value is not None:
            resolved[field] = (value, "legacy")

    # Dual-write the master tracks store. `_safe_upsert_track` commits the
    # Request's own enrichment first, so a store-write failure never regresses it
    # — the store is strictly additive (#541).
    if resolved:
        values = {field: value for field, (value, _src) in resolved.items()}
        sources = {field: src for field, (_value, src) in resolved.items()}
        _safe_upsert_track(
            db,
            identity=TrackIdentity(
                title=request.song_title,
                artist=request.artist,
                signature=signature,
                isrc=resolved_isrc,
                soundcharts_uuid=resolved_uuid,
            ),
            values=values,
            sources=sources,
            request_id=request_id,
        )
    else:
        db.commit()
    logger.info(
        "Enriched request %d: genre=%s, bpm=%s, key=%s",
        request_id,
        request.genre,
        request.bpm,
        request.musical_key,
    )


def _enrich_musicbrainz_genre(request: Request, resolved: dict[str, tuple[object, str]]) -> None:
    """Fill a missing genre from the artist-level MusicBrainz lookup."""
    request_id = request.id
    if not request.genre and request.artist:
        try:
            genre = lookup_artist_genre(request.artist)
            if genre:
                request.genre = genre
                resolved["genre"] = (genre, "musicbrainz")
        except Exception as exc:
            logger.warning(
                "MusicBrainz enrichment failed for request %d (%s)",
                request_id,
                type(exc).__name__,
            )


def _enrich_beatport(
    db: Session,
    request: Request,
    *,
    user,
    search_query: str,
    prefer_original: bool,
    resolved: dict[str, tuple[object, str]],
    resolved_isrc: str | None,
) -> str | None:
    """Fill missing BPM/key and optional genre from the user's Beatport account."""
    request_id = request.id
    if not request.bpm or not request.musical_key or not request.genre:
        if user and user.beatport_access_token:
            try:
                from app.services.providers.beatport_catalog import search_beatport_tracks

                results = search_beatport_tracks(db, user, search_query, limit=5)
                logger.info(
                    "Beatport returned %d results for request %d",
                    len(results) if results else 0,
                    request_id,
                )
                if results:
                    best = find_best_match(
                        results,
                        request.song_title,
                        request.artist,
                        prefer_original=prefer_original,
                    )
                    if best:
                        logger.info(
                            "Beatport best for %d: '%s' by '%s' bpm=%s key=%s mix=%s",
                            request_id,
                            best.title,
                            best.artist,
                            best.bpm,
                            best.key,
                            best.mix_name,
                        )
                        _apply_enrichment_result(
                            request, best, source="beatport", resolved=resolved, with_genre=True
                        )
                        if getattr(best, "isrc", None):
                            resolved_isrc = best.isrc
                    else:
                        logger.info("Beatport: no match for request %d", request_id)
            except Exception as exc:
                logger.warning(
                    "Beatport enrichment failed for request %d (%s)",
                    request_id,
                    type(exc).__name__,
                )

    return resolved_isrc


def _enrich_tidal(
    db: Session,
    request: Request,
    *,
    user,
    search_query: str,
    prefer_original: bool,
    resolved: dict[str, tuple[object, str]],
    resolved_isrc: str | None,
) -> str | None:
    """Fill missing BPM/key from Tidal when the user has a linked account."""
    request_id = request.id
    if not request.bpm or not request.musical_key:
        if user and user.tidal_access_token:
            try:
                from app.services.providers.tidal_search import search_tidal_tracks

                results = search_tidal_tracks(db, user, search_query, limit=5)
                logger.info(
                    "Tidal returned %d results for request %d",
                    len(results) if results else 0,
                    request_id,
                )
                if results:
                    best = find_best_match(
                        results,
                        request.song_title,
                        request.artist,
                        prefer_original=prefer_original,
                    )
                    if best:
                        logger.info(
                            "Tidal best for %d: '%s' by '%s' bpm=%s key=%s",
                            request_id,
                            best.title,
                            best.artist,
                            best.bpm,
                            getattr(best, "key", None),
                        )
                        _apply_enrichment_result(request, best, source="tidal", resolved=resolved)
                        if getattr(best, "isrc", None):
                            resolved_isrc = best.isrc
                    else:
                        logger.info("Tidal: no match for request %d", request_id)
            except Exception as exc:
                logger.warning(
                    "Tidal enrichment failed for request %d (%s)",
                    request_id,
                    type(exc).__name__,
                )

    return resolved_isrc


def _resolve_soundcharts_audio_features(
    request: Request,
    *,
    resolved: dict[str, tuple[object, str]],
    resolved_isrc: str | None,
    cached,
) -> str | None:
    """Fill gated audio-only features when an ISRC and incomplete store row exist."""
    request_id = request.id
    resolved_uuid: str | None = None
    if (
        get_settings().soundcharts_audio_features_enabled
        and resolved_isrc
        and (cached is None or cached.energy is None)
    ):
        try:
            from app.services.providers.soundcharts import get_song_features_by_isrc

            feats = get_song_features_by_isrc(resolved_isrc)
            if feats:
                resolved_uuid = feats.soundcharts_uuid or None
                resolved.update(_soundcharts_audio_values(feats))
        except Exception as exc:
            logger.warning(
                "Soundcharts audio-features lookup failed for request %d (%s)",
                request_id,
                type(exc).__name__,
            )

    return resolved_uuid


def _resolve_provider_metadata_and_audio(
    db: Session,
    request: Request,
    *,
    user,
    search_query: str,
    prefer_original: bool,
    source_svc: str | None,
    source_track_id: str | None,
    resolved: dict[str, tuple[object, str]],
    resolved_isrc: str | None,
    cached,
) -> tuple[str | None, str | None, float | None]:
    """Run provider resolution in priority order, then apply event-local BPM correction."""
    direct_result = resolve_direct_source_track(
        db,
        request,
        user=user,
        source_svc=source_svc,
        source_track_id=source_track_id,
        resolved_isrc=resolved_isrc,
        logger=logger,
    )
    resolved_isrc = _apply_source_resolution(request, resolved, direct_result)
    isrc_result = resolve_spotify_isrc_and_tidal_match(
        db,
        request,
        user=user,
        source_svc=source_svc,
        resolved_isrc=resolved_isrc,
        settings_provider=get_settings,
        isrc_resolver=_get_isrc_from_spotify,
        logger=logger,
    )
    resolved_isrc = _apply_source_resolution(request, resolved, isrc_result)
    _enrich_musicbrainz_genre(request, resolved)
    resolved_isrc = _enrich_beatport(
        db,
        request,
        user=user,
        search_query=search_query,
        prefer_original=prefer_original,
        resolved=resolved,
        resolved_isrc=resolved_isrc,
    )
    resolved_isrc = _enrich_tidal(
        db,
        request,
        user=user,
        search_query=search_query,
        prefer_original=prefer_original,
        resolved=resolved,
        resolved_isrc=resolved_isrc,
    )
    if request.musical_key:
        request.musical_key = normalize_key(request.musical_key)

    # Keep the canonical provider BPM for the store; correction is event-local.
    canonical_bpm = request.bpm
    _apply_bpm_context_correction(db, request)
    resolved_uuid = _resolve_soundcharts_audio_features(
        request, resolved=resolved, resolved_isrc=resolved_isrc, cached=cached
    )
    return resolved_isrc, resolved_uuid, canonical_bpm


def enrich_request_metadata(db: Session, request_id: int) -> None:
    """Background task: resolve a request's metadata and dual-write the master store.

    Fills missing genre/BPM/key on the Request (existing UI) AND writes a master
    `tracks` row cache-aside (#541): a trusted complete store row is reused with zero
    provider calls; otherwise the provider cascade runs (module docstring) and the
    resolved fields are upserted with per-field provenance. An already-complete
    Request still SEEDS the store (so search-result submissions populate it too).
    Results are fuzzy-matched against the request to avoid enriching from a wrong
    track. Best-effort: a store-write failure never regresses the Request's own
    commit. The module-level docstring documents the full cascade + store semantics.
    """
    # Re-fetch request in this background task's context
    request = db.query(Request).filter(Request.id == request_id).first()
    if not request:
        return

    # dedupe_signature is the same key the pool import uses, so a request and a
    # later pool-import of the same recording collapse to one tracks row.
    from app.services.tracks.identity import dedupe_signature

    sig = dedupe_signature(request.artist, request.song_title)

    if request.genre and request.bpm and request.musical_key:
        # Already complete on the Request — but still SEED the store so repeats can
        # reuse it. Search-result submissions arrive complete and skip the cascade,
        # so they would otherwise never populate the store (#541).
        _seed_complete_request(db, request, sig)
        # The complete path must not bypass energy backfill: when the gate is on
        # and the seeded row lacks energy, fetch Soundcharts audio features onto it
        # (the core cascade still never runs here).
        if get_settings().soundcharts_audio_features_enabled:
            cached = get_track(db, isrc=request.isrc, signature=sig)
            if cached is not None and cached.energy is None:
                _backfill_energy_for_cached(db, request, cached, sig)
        return

    # Cache-aside short-circuit: if the master store already has this recording
    # fully resolved BY REAL PROVIDERS, copy the missing fields down and skip ALL
    # providers — the dedupe win that makes the same song requested at two events
    # cost one set of API calls, not two (#541). A trio that is only ``legacy``
    # sourced is NOT authoritative — fall through so real providers can upgrade it.
    req_isrc = normalize_isrc(request.isrc)
    cached = get_track(db, isrc=req_isrc, signature=sig)
    # A signature fallback must NOT serve a DIFFERENT recording: if the request
    # carries an ISRC but the cached row has a different non-null ISRC (same
    # artist/title, different release/remaster), fall through to the providers so
    # the request's own recording is resolved (#552). An ISRC-less cached row is
    # still trusted, and gets the request's ISRC backfilled below.
    isrc_compatible = req_isrc is None or cached is None or cached.isrc in (None, req_isrc)
    if cached is not None and isrc_compatible and _trio_trusted(cached):
        if not request.genre:
            request.genre = cached.genre
        if not request.bpm:
            request.bpm = cached.bpm
        if not request.musical_key:
            request.musical_key = cached.musical_key
        # Backfill the request's ISRC onto a previously ISRC-less row: the ISRC
        # lookup above missed, so this cannot collide with another row's ISRC.
        if req_isrc and cached.isrc is None:
            cached.isrc = req_isrc
        # The trio (genre/bpm/key) is complete, so the full provider cascade is
        # skipped. But energy may still be missing on this row — when the gate is
        # on, backfill ONLY the Soundcharts audio features onto the existing row
        # (spec §2/§4/§5.4/§7: "energy backfills later"). The core cascade stays
        # skipped, preserving the zero-extra-core-API-calls dedupe win.
        if get_settings().soundcharts_audio_features_enabled and cached.energy is None:
            _backfill_energy_for_cached(db, request, cached, sig)
        # Context-correct the served BPM for THIS event (the cached value is canonical;
        # half/double-time correction is per-event and must not be skipped on a hit).
        _apply_bpm_context_correction(db, request)
        db.commit()
        logger.info(
            "Request %d served from track store (sig=%s): genre=%s bpm=%s key=%s",
            request_id,
            sig,
            request.genre,
            request.bpm,
            request.musical_key,
        )
        return

    # Per-field provenance accumulator: field -> (value, source). Populated
    # alongside the Request writes so the store dual-write below carries accurate
    # sources without post-hoc guessing.
    resolved: dict[str, tuple[object, str]] = {}
    # Seed from the Request's own ISRC (carried from the chosen search result, #552)
    # so the store identity is ISRC-first even before any provider resolves one;
    # provider hits below may still set it if the request arrived without one.
    resolved_isrc: str | None = request.isrc

    user = request.event.created_by
    search_query = f"{primary_artist(request.artist)} {request.song_title}"
    prefer_original = not is_remix_title(request.song_title)

    # Identify the source service and track ID from source_url
    source_svc, source_track_id = _extract_source_track_id(request.source_url)

    logger.info(
        "Enriching request %d: '%s' by '%s' | query='%s' prefer_original=%s | "
        "source_url=%s (svc=%s, id=%s) | existing: genre=%s bpm=%s key=%s",
        request_id,
        request.song_title,
        request.artist,
        search_query,
        prefer_original,
        request.source_url,
        source_svc,
        source_track_id,
        request.genre,
        request.bpm,
        request.musical_key,
    )

    resolved_isrc, resolved_uuid, canonical_bpm = _resolve_provider_metadata_and_audio(
        db,
        request,
        user=user,
        search_query=search_query,
        prefer_original=prefer_original,
        source_svc=source_svc,
        source_track_id=source_track_id,
        resolved=resolved,
        resolved_isrc=resolved_isrc,
        cached=cached,
    )

    _persist_enrichment_results(
        db,
        request,
        signature=sig,
        resolved=resolved,
        resolved_isrc=resolved_isrc,
        resolved_uuid=resolved_uuid,
        canonical_bpm=canonical_bpm,
    )
