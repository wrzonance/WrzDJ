"""MusicBrainz artist verification for recommendation results.

Checks each artist against MusicBrainz to confirm they are a real,
community-curated artist (not AI-generated filler).  Results are
cached in the mb_artist_cache table so subsequent runs are instant.

ListenBrainz popularity gate (Layer 3): after MB verification, artists
with verified=True are checked against ListenBrainz for actual listener
counts.  Artists with fewer than LB_MIN_USER_COUNT unique listeners are
rejected as likely stock/AI filler.
"""

import logging
from collections.abc import Iterable
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.mb_artist_cache import MbArtistCache
from app.services.providers.musicbrainz import check_artist_exists
from app.services.track_normalizer import split_artists

# Cached entries older than this are re-verified against MusicBrainz
CACHE_TTL_DAYS = 30

# Minimum unique ListenBrainz listeners to pass the popularity gate
LB_MIN_USER_COUNT = 5

logger = logging.getLogger(__name__)


def _normalize(name: str) -> str:
    return name.lower().strip()


def _backfill_lb_popularity(db: Session, normalized_map: dict[str, list[str]]) -> None:  # noqa: E501
    """Backfill ListenBrainz popularity for verified artists missing LB data.

    Queries cache for rows where verified=True, mbid is not None,
    and lb_user_count is None. Fetches popularity in a single batch
    POST and writes results back to the cache rows.
    """
    from app.services.providers.listenbrainz import fetch_artist_popularity

    # Find verified artists with MBIDs that haven't been checked against LB yet
    rows_needing_lb = (
        db.query(MbArtistCache)
        .filter(
            MbArtistCache.artist_name.in_(list(normalized_map.keys())),
            MbArtistCache.verified == True,  # noqa: E712
            MbArtistCache.mbid.isnot(None),
            MbArtistCache.lb_user_count.is_(None),
        )
        .all()
    )

    if not rows_needing_lb:
        return

    mbid_to_rows: dict[str, list[MbArtistCache]] = {}
    for row in rows_needing_lb:
        mbid_to_rows.setdefault(row.mbid, []).append(row)

    mbids = list(mbid_to_rows.keys())
    lb_data = fetch_artist_popularity(mbids)

    # On LB failure (empty dict returned), leave lb_user_count as None (pass-through)
    if not lb_data and mbids:
        logger.info("ListenBrainz returned no data for %d MBIDs — skipping LB gate", len(mbids))
        return

    for mbid, rows in mbid_to_rows.items():
        popularity = lb_data.get(mbid)
        for row in rows:
            if popularity is not None:
                row.lb_listen_count = popularity.get("total_listen_count")
                row.lb_user_count = popularity.get("total_user_count")
            else:
                # MBID not in LB response — store 0 to avoid re-querying
                row.lb_listen_count = 0
                row.lb_user_count = 0

    logger.info(
        "LB backfill: %d artists checked, %d found in LB",
        len(mbids),
        sum(1 for m in mbids if m in lb_data),
    )


def _apply_lb_gate(
    result: dict[str, bool],
    normalized_map: dict[str, list[str]],
    db: Session,
) -> None:
    """Apply ListenBrainz popularity gate to verified artists.

    Artists with lb_user_count < LB_MIN_USER_COUNT are rejected.
    Artists with lb_user_count=None (API failure or no MBID) pass through.
    """
    # Fetch cache rows for all normalized names
    cache_rows = (
        db.query(MbArtistCache)
        .filter(MbArtistCache.artist_name.in_(list(normalized_map.keys())))
        .all()
    )
    cache_map = {row.artist_name: row for row in cache_rows}

    for norm_name, original_names in normalized_map.items():
        row = cache_map.get(norm_name)
        if not row or row.lb_user_count is None:
            continue  # Pass through: no LB data available
        if row.lb_user_count < LB_MIN_USER_COUNT:
            for orig in original_names:
                result[orig] = False


def verify_artists_batch(db: Session, artist_names: Iterable[str]) -> dict[str, bool]:
    """Verify a batch of artist names against MusicBrainz.

    Returns a mapping of original artist name -> verified boolean.
    Deduplicates names, checks the DB cache first, then calls the
    MusicBrainz API for any uncached artists (1 req/sec throttled).

    After MB verification, applies the ListenBrainz popularity gate
    to reject artists with very few actual listeners.
    """
    # Build mapping: normalized -> set of original names
    # Split multi-artist strings so each individual gets verified separately
    normalized_map: dict[str, list[str]] = {}
    composite_originals: dict[str, list[str]] = {}  # original composite -> individual names
    for name in artist_names:
        if not name or not name.strip():
            continue
        individuals = split_artists(name)
        if len(individuals) > 1:
            composite_originals[name] = individuals
        for individual in individuals:
            key = _normalize(individual)
            if not key:
                continue
            if key not in normalized_map:
                normalized_map[key] = []
            normalized_map[key].append(individual)

    if not normalized_map:
        return {}

    # Query cache for all normalized names (TTL: only trust recent entries)
    cutoff = utcnow() - timedelta(days=CACHE_TTL_DAYS)
    cached = (
        db.query(MbArtistCache)
        .filter(
            MbArtistCache.artist_name.in_(list(normalized_map.keys())),
            MbArtistCache.created_at >= cutoff,
        )
        .all()
    )
    cached_map = {c.artist_name: c.verified for c in cached}

    cached_count = 0
    api_count = 0
    result: dict[str, bool] = {}

    for norm_name, original_names in normalized_map.items():
        if norm_name in cached_map:
            verified = cached_map[norm_name]
            cached_count += 1
        else:
            # Call MusicBrainz API (throttled to 1 req/sec)
            verified, mbid = check_artist_exists(norm_name)
            api_count += 1
            # Upsert: update existing expired entry or create new
            existing = (
                db.query(MbArtistCache).filter(MbArtistCache.artist_name == norm_name).first()
            )
            if existing:
                existing.verified = verified
                existing.mbid = mbid
                existing.created_at = utcnow()
            else:
                db.add(
                    MbArtistCache(
                        artist_name=norm_name,
                        mbid=mbid,
                        verified=verified,
                    )
                )

        for orig in original_names:
            result[orig] = verified

    # For composite artist names, mark as verified if ANY constituent is verified
    for composite, individuals in composite_originals.items():
        any_verified = any(result.get(ind, False) for ind in individuals)
        result[composite] = any_verified

    # Flush new/updated cache rows so LB queries can find them
    db.flush()

    # ListenBrainz popularity gate (Layer 3)
    _backfill_lb_popularity(db, normalized_map)
    _apply_lb_gate(result, normalized_map, db)

    # Re-evaluate composites after LB gate may have changed individual results
    for composite, individuals in composite_originals.items():
        any_verified = any(result.get(ind, False) for ind in individuals)
        result[composite] = any_verified

    if api_count > 0:
        db.commit()

    logger.info(
        "MB verification: %d cached, %d API calls, %d unique artists",
        cached_count,
        api_count,
        len(normalized_map),
    )

    return result
