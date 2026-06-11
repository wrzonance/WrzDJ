"""WrzDJSet TrackVibe batch LLM enrichment (issue #391).

Fills the global ``track_vibes`` cache for a set's pool via the LLM gateway,
batching BATCH_SIZE tracks per forced-``tool_use`` dispatch (defensive parsing
mirrors ``services/recommendation/llm_client.py``). The cache is GLOBAL: any
row matching (track key, PROMPT_VERSION, SCHEMA_VERSION) — regardless of
provider/model — counts as cached, so a second DJ pays zero even on a
different connector. Bumping PROMPT_VERSION lazily invalidates old rows.

Telemetry rule: warnings log counts only — never prompt/completion/track content.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.set import Set
from app.models.set_pool import SetPoolTrack
from app.models.track_vibe import TrackVibe
from app.models.user import User
from app.services.llm.base import ChatRequest, ChatResponse, Message, ToolSpec
from app.services.llm.exceptions import LlmError, NoLlmConfigured
from app.services.llm.gateway import Gateway

logger = logging.getLogger(__name__)

PURPOSE = "vibe_enrichment"
PROMPT_VERSION = "v1"
SCHEMA_VERSION = "v1"
BATCH_SIZE = 20
MAX_TOKENS = 4096
TRANSITIONAL_ROLES = frozenset({"intro", "build", "peak", "cool", "any"})
VIBES_TOOL_NAME = "submit_track_vibes"

SYSTEM_PROMPT = """You are a music-metadata expert annotating tracks for DJ set planning.

For each numbered track estimate:
- energy: integer 0-10 (0 = ambient/chill, 10 = peak-time mainstage intensity)
- mood: one or two lowercase words (e.g. "euphoric", "dark", "feel-good")
- era: release decade or scene era (e.g. "90s", "2010s", "classic house")
- sing_along: true if crowds commonly sing the hook out loud
- dance_floor: true if the track reliably keeps a dance floor moving
- transitional_role: where it fits in a set arc — "intro", "build", "peak", "cool", or "any"
- confidence: 0-1 — how certain you are you know this exact track
  (0.2 = guessing from the title, 0.9 = you know the track well)

Be honest with confidence: if you do not recognize a track, keep confidence
below 0.4 and infer from title/artist/genre conventions. Return one entry per
input track, matched by index."""

VIBES_TOOL_DESCRIPTION = (
    "Submit vibe annotations for the input tracks — one entry per track, matched by index."
)

VIBES_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "tracks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "description": "Input track number"},
                    "energy": {"type": "integer", "minimum": 0, "maximum": 10},
                    "mood": {"type": "string", "description": "1-2 lowercase words"},
                    "era": {"type": "string", "description": "decade or scene era"},
                    "sing_along": {"type": "boolean"},
                    "dance_floor": {"type": "boolean"},
                    "transitional_role": {
                        "type": "string",
                        "enum": ["intro", "build", "peak", "cool", "any"],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["index", "energy", "confidence"],
            },
        }
    },
    "required": ["tracks"],
}


def vibe_key(track: SetPoolTrack) -> str:
    """Global cache key — namespaced track_id, else the dedupe signature."""
    return track.track_id or f"sig:{track.dedupe_sig}"


@dataclass(frozen=True)
class VibeEnrichmentStats:
    enriched: int
    cached: int
    failed: int
    llm_calls: int


def _cached_keys(db: Session, keys: Iterable[str]) -> set[str]:
    """Keys that already have ANY TrackVibe row at the current prompt/schema version."""
    keys = list(keys)
    if not keys:
        return set()
    rows = (
        db.query(TrackVibe.track_id)
        .filter(
            TrackVibe.track_id.in_(keys),
            TrackVibe.prompt_version == PROMPT_VERSION,
            TrackVibe.schema_version == SCHEMA_VERSION,
        )
        .all()
    )
    return {row[0] for row in rows}


def _track_line(index: int, track: SetPoolTrack) -> str:
    line = f"{index}. {track.artist} — {track.title}"
    if track.genre and track.bpm:
        line += f" ({track.genre}, {track.bpm:.0f} BPM)"
    elif track.genre:
        line += f" ({track.genre})"
    elif track.bpm:
        line += f" ({track.bpm:.0f} BPM)"
    return line


def _build_request(batch: list[SetPoolTrack]) -> ChatRequest:
    lines = [_track_line(i, track) for i, track in enumerate(batch)]
    return ChatRequest(
        messages=[Message(role="user", content="\n".join(lines))],
        system=SYSTEM_PROMPT,
        tools=[
            ToolSpec(
                name=VIBES_TOOL_NAME,
                description=VIBES_TOOL_DESCRIPTION,
                input_schema=VIBES_TOOL_SCHEMA,
            )
        ],
        force_tool=VIBES_TOOL_NAME,
        max_tokens=MAX_TOKENS,
        # IMPORTANT design deviation: issue #391 asked for model_hint="fast",
        # but the gateway has no speed-tier concept — ChatRequest.model is a
        # hard override of the connector's configured model. Passing None lets
        # the connector's own configured model govern.
        model=None,
    )


def _clamp(value: object, lo: float, hi: float, *, as_int: bool) -> int | float | None:
    """Clamp a numeric into [lo, hi] (rounded when ``as_int``). Bools / non-numerics -> None."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    clamped = max(lo, min(hi, value))
    return round(clamped) if as_int else float(clamped)


def _clean_str(value: object) -> str | None:
    """Strings only: strip + truncate to 50 chars; empty -> None."""
    if not isinstance(value, str):
        return None
    return value.strip()[:50] or None


def _parse_items(response: ChatResponse, batch: list[SetPoolTrack]) -> dict[int, dict]:
    """Defensively extract per-track vibe fields from the forced tool call.

    Returns ``{batch_index: vibe_fields}`` — first entry per index wins;
    out-of-range / malformed items are skipped rather than raising.
    """
    parsed: dict[int, dict] = {}
    for tc in response.tool_calls or []:
        if tc.name != VIBES_TOOL_NAME:
            continue
        payload = tc.input if isinstance(tc.input, dict) else {}
        items = payload.get("tracks")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            # isinstance(True, int) is True — exclude bools explicitly.
            if isinstance(index, bool) or not isinstance(index, int):
                continue
            if not (0 <= index < len(batch)) or index in parsed:
                continue
            role = item.get("transitional_role")
            parsed[index] = {
                "energy": _clamp(item.get("energy"), 0, 10, as_int=True),
                "mood": _clean_str(item.get("mood")),
                "era": _clean_str(item.get("era")),
                "sing_along": (
                    item.get("sing_along") if isinstance(item.get("sing_along"), bool) else None
                ),
                "dance_floor": (
                    item.get("dance_floor") if isinstance(item.get("dance_floor"), bool) else None
                ),
                "transitional_role": role if role in TRANSITIONAL_ROLES else None,
                "confidence": _clamp(item.get("confidence"), 0.0, 1.0, as_int=False),
            }
    return parsed


async def enrich_pool_vibes(db: Session, actor: User, set_obj: Set) -> VibeEnrichmentStats:
    """Enrich the set's pool with LLM vibe annotations, using the global cache.

    Raises :class:`NoLlmConfigured` (caller maps it to 400); any other
    :class:`LlmError` aborts remaining batches (no provider hammering) and
    counts the unprocessed tracks as failed.
    """
    tracks = db.query(SetPoolTrack).filter(SetPoolTrack.set_id == set_obj.id).all()
    by_key = {vibe_key(t): t for t in tracks}  # de-dupes within the pool

    already = _cached_keys(db, by_key)
    cached = len(already)
    missing = [k for k in by_key if k not in already]

    enriched = 0
    failed = 0
    llm_calls = 0

    batches = [missing[i : i + BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]
    for batch_no, key_batch in enumerate(batches):
        batch = [by_key[k] for k in key_batch]
        llm_calls += 1
        try:
            response = await Gateway.dispatch(db, actor, _build_request(batch), purpose=PURPOSE)
        except NoLlmConfigured:
            raise
        except LlmError as exc:
            remaining = sum(len(b) for b in batches[batch_no:])
            failed += remaining
            logger.warning(
                "vibe enrichment aborted on %s: %d tracks unprocessed across %d batches",
                type(exc).__name__,
                remaining,
                len(batches) - batch_no,
            )
            break

        parsed = _parse_items(response, batch)
        failed += len(batch) - len(parsed)

        # Race safety: a concurrent enrichment may have inserted some of these
        # keys since the initial cache check — re-check just before inserting.
        existing_now = _cached_keys(db, (vibe_key(batch[i]) for i in parsed))
        rows_added = 0
        for index, fields in parsed.items():
            key = vibe_key(batch[index])
            if key in existing_now:
                cached += 1
                continue
            db.add(
                TrackVibe(
                    track_id=key,
                    **fields,
                    llm_provider=response.provider or "unknown",
                    llm_model=response.model or "unknown",
                    prompt_version=PROMPT_VERSION,
                    schema_version=SCHEMA_VERSION,
                )
            )
            rows_added += 1
        try:
            db.commit()
            enriched += rows_added
        except IntegrityError:
            # Concurrent enrichment won the race between re-check and commit.
            db.rollback()
            cached += rows_added

    return VibeEnrichmentStats(enriched=enriched, cached=cached, failed=failed, llm_calls=llm_calls)
