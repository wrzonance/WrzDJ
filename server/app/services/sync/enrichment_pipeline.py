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

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.models.request import Request, RequestStatus
from app.services.musicbrainz import lookup_artist_genre
from app.services.request import normalize_key
from app.services.track_normalizer import (
    artist_match_score,
    fuzzy_match_score,
    is_original_mix_name,
    is_remix_title,
    normalize_bpm_to_context,
    normalize_isrc,
    primary_artist,
    score_track_match,
)
from app.services.tracks.provenance import is_cache_authoritative
from app.services.tracks.store import TrackIdentity, get_track, upsert_track

logger = logging.getLogger(__name__)

# URL patterns for extracting track IDs from source URLs
_SPOTIFY_URL_RE = re.compile(r"open\.spotify\.com/track/(\w+)")
_BEATPORT_URL_RE = re.compile(r"beatport\.com/track/[^/]+/(\d+)")
_TIDAL_URL_RE = re.compile(r"tidal\.com/(?:browse/)?track/(\d+)")


def _find_best_match(
    results,
    title: str,
    artist: str,
    min_score: float = 0.4,
    min_artist_score: float = 0.35,
    prefer_original: bool = True,
):
    """Find the best fuzzy match from search results.

    Scores each result by title (60%) + artist (40%) similarity.
    Returns the best match above min_score, or None if no good match.

    A separate min_artist_score floor prevents a perfect title match
    from carrying a completely wrong artist (e.g., "Feel the Beat" by
    LB aka LABAT matching a request for Darude).

    When prefer_original is True, applies a small bonus (+0.1) for
    results that look like the original version (Beatport mix_name
    matches "Original Mix", "Extended Mix", etc.) and a penalty (-0.1)
    for results with detected remix patterns in the title (Tidal).
    This breaks ties between "Surrender (Original Mix)" at 132 BPM and
    "Surrender (Hardstyle Remix)" at 165 BPM without overriding a
    genuinely better title/artist match.

    When multiple results have identical scores, a BPM consensus
    tiebreaker (+0.01) favors the version whose BPM matches the most
    common BPM among all results.
    """
    logger.info(
        "_find_best_match: title='%s' artist='%s' prefer_original=%s (%d results)",
        title,
        artist,
        prefer_original,
        len(results),
    )

    # Compute modal BPM for consensus tiebreaker
    bpm_counts: dict[int, int] = {}
    for result in results:
        bpm = getattr(result, "bpm", None)
        if bpm:
            rounded = round(float(bpm))
            bpm_counts[rounded] = bpm_counts.get(rounded, 0) + 1
    modal_bpm = max(bpm_counts, key=bpm_counts.get) if bpm_counts else None

    best = None
    best_score = 0.0
    for i, result in enumerate(results):
        title_score = fuzzy_match_score(title, result.title)
        artist_score = artist_match_score(artist, result.artist)
        if artist_score < min_artist_score:
            logger.info(
                "  [%d] SKIP artist_score=%.3f < %.2f | title=%s artist=%s",
                i,
                artist_score,
                min_artist_score,
                result.title,
                result.artist,
            )
            continue
        combined = score_track_match(title_score, artist_score)
        version_adj = 0.0

        if prefer_original:
            mix_name = getattr(result, "mix_name", None)
            if mix_name:
                # Beatport: structured mix_name available
                if is_original_mix_name(mix_name):
                    version_adj = 0.1
                    combined += 0.1
                # Named remix/bootleg/rework in mix_name → no bonus
            else:
                # Tidal/other: check title for remix patterns
                if is_remix_title(result.title):
                    version_adj = -0.1
                    combined -= 0.1

        # BPM consensus tiebreaker: prefer modal BPM among results
        bpm_adj = 0.0
        result_bpm = getattr(result, "bpm", None)
        if modal_bpm and result_bpm and round(float(result_bpm)) == modal_bpm:
            bpm_adj = 0.01
            combined += 0.01

        logger.info(
            "  [%d] title=%s artist=%s bpm=%s mix=%s | "
            "title_sc=%.3f artist_sc=%.3f ver_adj=%+.02f bpm_adj=%+.003f => combined=%.4f",
            i,
            result.title,
            result.artist,
            getattr(result, "bpm", "?"),
            getattr(result, "mix_name", None) or "-",
            title_score,
            artist_score,
            version_adj,
            bpm_adj,
            combined,
        )

        if combined > best_score:
            best_score = combined
            best = result

    if best and best_score >= min_score:
        logger.info(
            "  BEST: title=%s artist=%s bpm=%s (score=%.4f)",
            best.title,
            best.artist,
            getattr(best, "bpm", "?"),
            best_score,
        )
        return best

    logger.info("  NO MATCH (best_score=%.4f < min=%.2f)", best_score, min_score)
    return None


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


def _get_isrc_from_spotify(source_url: str | None) -> str | None:
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
        from app.services.spotify import _get_spotify_client

        sp = _get_spotify_client()
        track = sp.track(m.group(1))
        return track.get("external_ids", {}).get("isrc")
    except Exception:
        logger.warning("Failed to fetch ISRC from Spotify for %s", source_url)
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
    if with_genre and not request.genre and getattr(best, "genre", None):
        request.genre = best.genre
        resolved["genre"] = (best.genre, source)
    if not request.bpm and best.bpm:
        request.bpm = float(best.bpm)
        resolved["bpm"] = (float(best.bpm), source)
    if not request.musical_key and getattr(best, "key", None):
        normalized = normalize_key(best.key)
        request.musical_key = normalized
        resolved["musical_key"] = (normalized, source)


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
    resolved_isrc = cached.isrc or _get_isrc_from_spotify(request.source_url)
    if not resolved_isrc:
        return
    try:
        from app.services.soundcharts import get_song_features_by_isrc

        feats = get_song_features_by_isrc(resolved_isrc)
    except Exception:
        logger.warning("Soundcharts energy backfill lookup failed for request %d", request.id)
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
    except Exception:
        db.rollback()
        logger.warning("Track store upsert failed for request %d", request_id)


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
    from app.services.setbuilder.pool import dedupe_signature

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

    # 0. Direct fetch: when source_url points to Beatport or Tidal, skip search entirely
    if source_svc == "beatport" and source_track_id:
        if user and user.beatport_access_token and (not request.bpm or not request.musical_key):
            try:
                from app.services.beatport import get_beatport_track

                direct = get_beatport_track(db, user, source_track_id)
                if direct:
                    logger.info(
                        "Beatport direct fetch for %d: '%s' bpm=%s key=%s",
                        request_id,
                        direct.title,
                        direct.bpm,
                        direct.key,
                    )
                    _apply_enrichment_result(
                        request, direct, source="beatport", resolved=resolved, with_genre=True
                    )
                    if getattr(direct, "isrc", None):
                        resolved_isrc = direct.isrc
            except Exception:
                logger.warning("Beatport direct fetch failed for request %d", request_id)

    if source_svc == "tidal" and source_track_id:
        if user and user.tidal_access_token and (not request.bpm or not request.musical_key):
            try:
                from app.services.tidal import get_tidal_track_by_id

                direct = get_tidal_track_by_id(db, user, source_track_id)
                if direct:
                    logger.info(
                        "Tidal direct fetch for %d: '%s' bpm=%s key=%s",
                        request_id,
                        direct.title,
                        direct.bpm,
                        direct.key,
                    )
                    _apply_enrichment_result(request, direct, source="tidal", resolved=resolved)
                    if getattr(direct, "isrc", None):
                        resolved_isrc = direct.isrc
            except Exception:
                logger.warning("Tidal direct fetch failed for request %d", request_id)

    # 0b. Spotify URL → ISRC. Capture the ISRC INDEPENDENTLY of Tidal auth (so the
    # Soundcharts lookup isn't starved for DJs without a Tidal token), but ONLY when
    # a consumer actually exists — otherwise the external Spotify call is wasted
    # (#541). The two consumers: the Tidal exact-match (needs a token + missing
    # bpm/key) and the Soundcharts audio-features lookup (needs the gate on).
    needs_isrc_for_tidal = bool(
        (not request.bpm or not request.musical_key) and user and user.tidal_access_token
    )
    needs_isrc_for_soundcharts = get_settings().soundcharts_audio_features_enabled
    if (
        source_svc == "spotify"
        and not resolved_isrc
        and (needs_isrc_for_tidal or needs_isrc_for_soundcharts)
    ):
        resolved_isrc = _get_isrc_from_spotify(request.source_url)

    # Exact Tidal match by ISRC needs a token and only helps when bpm/key are blank.
    if (
        source_svc == "spotify"
        and resolved_isrc
        and (not request.bpm or not request.musical_key)
        and user
        and user.tidal_access_token
    ):
        try:
            from app.services.tidal import search_tidal_by_isrc

            isrc_match = search_tidal_by_isrc(db, user, resolved_isrc)
            if isrc_match:
                logger.info(
                    "ISRC match for %d: '%s' by '%s' bpm=%s key=%s (ISRC=%s)",
                    request_id,
                    isrc_match.title,
                    isrc_match.artist,
                    isrc_match.bpm,
                    isrc_match.key,
                    resolved_isrc,
                )
                _apply_enrichment_result(request, isrc_match, source="tidal", resolved=resolved)
        except Exception:
            logger.warning("ISRC enrichment failed for request %d", request_id)

    # 1. MusicBrainz for genre (artist-level, free, rate-limited)
    if not request.genre and request.artist:
        try:
            genre = lookup_artist_genre(request.artist)
            if genre:
                request.genre = genre
                resolved["genre"] = (genre, "musicbrainz")
        except Exception:
            logger.warning("MusicBrainz enrichment failed for request %d", request_id)

    # 2. Beatport for BPM + key (and genre backfill if MusicBrainz missed)
    if not request.bpm or not request.musical_key or not request.genre:
        if user and user.beatport_access_token:
            try:
                from app.services.beatport import search_beatport_tracks

                results = search_beatport_tracks(db, user, search_query, limit=5)
                logger.info(
                    "Beatport returned %d results for request %d",
                    len(results) if results else 0,
                    request_id,
                )
                if results:
                    best = _find_best_match(
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
            except Exception:
                logger.warning("Beatport enrichment failed for request %d", request_id)

    # 3. Tidal for BPM + key (backup when Beatport didn't find them)
    if not request.bpm or not request.musical_key:
        if user and user.tidal_access_token:
            try:
                from app.services.tidal import search_tidal_tracks

                results = search_tidal_tracks(db, user, search_query, limit=5)
                logger.info(
                    "Tidal returned %d results for request %d",
                    len(results) if results else 0,
                    request_id,
                )
                if results:
                    best = _find_best_match(
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
            except Exception:
                logger.warning("Tidal enrichment failed for request %d", request_id)

    # Normalize key if we got one from enrichment
    if request.musical_key:
        request.musical_key = normalize_key(request.musical_key)

    # 4. BPM context correction: detect half-time/double-time from other event
    # tracks (shared with the cache-hit path via _apply_bpm_context_correction).
    # This mutates ONLY request.bpm — the event-specific corrected value must NOT
    # be written to the global store. The store keeps the canonical provider BPM
    # (resolved["bpm"]) so future cache hits at other events re-derive their own
    # per-event correction from it, instead of inheriting this event's tempo (#541).
    # Stash the canonical pre-correction value for the legacy store seed below: a
    # pre-supplied BPM is not in `resolved`, so the seed would otherwise persist the
    # event-corrected request.bpm globally.
    canonical_bpm = request.bpm
    _apply_bpm_context_correction(db, request)

    # 5. Soundcharts audio features (energy/danceability/…) — gated, dark by
    # default. Only when the flag is on, an ISRC is in hand, and the store row
    # lacks energy. bpm/key/genre stay with the existing cascade to avoid
    # equal-precedence churn; Soundcharts contributes audio features only.
    resolved_uuid: str | None = None
    if (
        get_settings().soundcharts_audio_features_enabled
        and resolved_isrc
        and (cached is None or cached.energy is None)
    ):
        try:
            from app.services.soundcharts import get_song_features_by_isrc

            feats = get_song_features_by_isrc(resolved_isrc)
            if feats:
                resolved_uuid = feats.soundcharts_uuid or None
                resolved.update(_soundcharts_audio_values(feats))
        except Exception:
            logger.warning("Soundcharts audio-features lookup failed for request %d", request_id)

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
                signature=sig,
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
