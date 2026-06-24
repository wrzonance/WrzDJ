"""Enrichment pipeline — fills missing genre/BPM/key on requests.

Sources (in priority order):
0. Direct fetch via source_url (Beatport/Tidal URL → exact track)
0b. ISRC matching (Spotify URL → ISRC → exact Tidal match)
1. MusicBrainz artist lookup (genre — artist-level, 1 req/sec rate limit)
2. Beatport search (BPM + key, backfill genre if MusicBrainz missed)
3. Tidal search (BPM + key backup when Beatport unavailable)
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
    primary_artist,
    score_track_match,
)
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


def enrich_request_metadata(db: Session, request_id: int) -> None:
    """Background task: fill missing genre/BPM/key on a request.

    Sources (in priority order):
    0. Direct fetch via source_url (Beatport/Tidal URL → exact track)
    0b. ISRC matching (Spotify URL → ISRC → exact Tidal match)
    1. MusicBrainz artist lookup (genre — artist-level, 1 req/sec rate limit)
    2. Beatport search (BPM + key, backfill genre if MusicBrainz missed)
    3. Tidal search (BPM + key backup when Beatport unavailable)

    Only queries sources for missing fields. Skips if all fields present.
    Results are fuzzy-matched against the request to avoid enriching
    with metadata from a wrong track.
    """
    # Re-fetch request in this background task's context
    request = db.query(Request).filter(Request.id == request_id).first()
    if not request:
        return

    if request.genre and request.bpm and request.musical_key:
        return  # Already complete

    # Cache-aside short-circuit: if the master store already has this recording
    # fully resolved, copy the missing fields down and skip ALL providers — the
    # dedupe win that makes the same song requested at two events cost one set of
    # API calls, not two (#541). dedupe_signature is the same key pool import uses.
    from app.services.setbuilder.pool import dedupe_signature

    sig = dedupe_signature(request.artist, request.song_title)
    cached = get_track(db, signature=sig)
    if cached is not None and cached.genre and cached.bpm and cached.musical_key:
        if not request.genre:
            request.genre = cached.genre
        if not request.bpm:
            request.bpm = cached.bpm
        if not request.musical_key:
            request.musical_key = cached.musical_key
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
    resolved_isrc: str | None = None

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

    # 0b. ISRC matching: Spotify URL → fetch ISRC → exact Tidal lookup
    if source_svc == "spotify" and (not request.bpm or not request.musical_key):
        if user and user.tidal_access_token:
            try:
                isrc = _get_isrc_from_spotify(request.source_url)
                if isrc:
                    resolved_isrc = isrc
                    from app.services.tidal import search_tidal_by_isrc

                    isrc_match = search_tidal_by_isrc(db, user, isrc)
                    if isrc_match:
                        logger.info(
                            "ISRC match for %d: '%s' by '%s' bpm=%s key=%s (ISRC=%s)",
                            request_id,
                            isrc_match.title,
                            isrc_match.artist,
                            isrc_match.bpm,
                            isrc_match.key,
                            isrc,
                        )
                        _apply_enrichment_result(
                            request, isrc_match, source="tidal", resolved=resolved
                        )
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

    # 4. BPM context correction: detect half-time/double-time from other event tracks
    if request.bpm:
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
                request_id,
                request.bpm,
                corrected,
                statistics.median(context_bpms),
            )
            request.bpm = corrected
            # Keep the store in sync with the context-corrected value, preserving
            # the original provider source (the correction is a refinement of it).
            if "bpm" in resolved:
                resolved["bpm"] = (corrected, resolved["bpm"][1])

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
                for field, value in audio_fields.items():
                    if value is not None:
                        resolved[field] = (value, "soundcharts")
        except Exception:
            logger.warning("Soundcharts audio-features lookup failed for request %d", request_id)

    # Dual-write the master tracks store. Wrapped so a store failure never
    # regresses the request's own commit — the store is strictly additive (#541).
    if resolved:
        values = {field: value for field, (value, _src) in resolved.items()}
        sources = {field: src for field, (_value, src) in resolved.items()}
        try:
            upsert_track(
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
                fetched_at=utcnow(),
            )
        except Exception:
            logger.warning("Track store upsert failed for request %d", request_id)

    db.commit()
    logger.info(
        "Enriched request %d: genre=%s, bpm=%s, key=%s",
        request_id,
        request.genre,
        request.bpm,
        request.musical_key,
    )
