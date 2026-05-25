"""LLM client for generating recommendation search queries via the Gateway.

The recommendation engine no longer talks directly to Anthropic — instead it
calls ``Gateway.dispatch(...)``, which routes to the actor DJ's connector (or
the org default). The forced tool_use semantics are preserved across providers
via ``services/llm/tool_translation.py``.

See ``docs/superpowers/specs/2026-05-24-admin-ai-oauth-design.md`` §7.
"""

from __future__ import annotations

import json
import logging

from anthropic import AsyncAnthropic
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.user import User
from app.services.llm.base import ChatRequest, Message, ToolSpec
from app.services.llm.gateway import Gateway
from app.services.recommendation.llm_hooks import LLMSuggestionQuery, LLMSuggestionResult
from app.services.recommendation.scorer import EventProfile, TrackProfile

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a DJ assistant helping curate song suggestions for a live event.

You understand music theory concepts relevant to DJing:
- BPM (beats per minute) and how tracks at similar tempos mix well
- Musical keys and the Camelot wheel for harmonic mixing
- Genre taxonomy (House, Tech House, Techno, Hip Hop, Pop, etc.)
- Artist-genre associations

You will receive:
- The DJ's natural language prompt
- A statistical profile of the event (average BPM, dominant keys/genres)
- The actual track list the DJ has accepted/played (with metadata)

Use ALL of this context to understand the DJ's current direction
and taste.

UNDERSTANDING DJ INTENT — TWO MODES:

1. "More of the same" — The DJ wants tracks that match the current vibe.
   Phrases: "more like these", "keep it going", "similar to [song/artist]".
   → Set target_bpm/key/genre to match the current event profile.

2. "Vibe shift" — The DJ wants to change direction.
   Phrases: "switch to house", "take it up to 128", "go darker",
   "transition to techno", "something completely different".
   → Set target_bpm/key/genre to the NEW direction, even if it differs
   significantly from the current profile. You are empowered to break
   away from the existing profile when the DJ asks for a change.

CRITICAL RULES:
1. NEVER recommend songs already in the track list. You are finding NEW music.
2. When the DJ says "like [song]" or "similar to [artist]", they mean
   musically similar — same vibe, energy, genre, era, or mood. They do NOT
   mean songs with similar words in the title. "More songs like Old Country
   Soul" means country songs with a similar soulful feel at a similar tempo,
   NOT songs with "Old", "Country", or "Soul" in the title.
3. Search queries should be ARTIST NAMES or GENRE TERMS that would lead to
   the right style of music, not fragments of the referenced song's title.
   Think: "What other artists make music that sounds like this?"
4. ALWAYS set target_bpm, target_key, and target_genre when you can infer
   them from context. These are critical scoring signals — tracks are ranked
   against these targets. Omitting them when the intent is clear will produce
   poorly ranked results.
5. For vibe shifts, set targets on ALL queries to the new direction. For
   "more of the same", set targets to match the current profile.
6. If rejected tracks are listed, AVOID recommending songs that are similar
   to the rejected ones — the DJ explicitly said no to those. Don't suggest
   the same artists or very similar styles unless the DJ's prompt specifically
   asks for that direction.
7. If a currently playing track is shown, factor it into your recommendations
   — the DJ is most likely looking for tracks that flow naturally from what's
   playing RIGHT NOW, not just the overall set profile.

Generate 1-6 search queries that would find matching tracks on
Tidal or Beatport. Each query should be a realistic search string
— preferably artist names, genre terms, or "artist genre" combos.

Include brief reasoning explaining why you chose each query."""

# Tool name kept stable so any cached tool_use traces remain decodable.
SEARCH_QUERIES_TOOL_NAME = "search_queries"

SEARCH_QUERIES_TOOL = {
    "name": SEARCH_QUERIES_TOOL_NAME,
    "description": (
        "Return structured search queries for finding tracks that match the DJ's intent."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "search_query": {
                            "type": "string",
                            "description": (
                                "Search string for Tidal/Beatport — use artist names,"
                                " genre terms, or 'artist genre' combos."
                                " Do NOT use fragments of a referenced song title."
                            ),
                        },
                        "target_bpm": {
                            "type": "number",
                            "description": (
                                "Target BPM — set this to signal the desired tempo."
                                " Critical for vibe shifts (e.g. 128 when switching to house)."
                                " Results are scored against this value."
                            ),
                        },
                        "target_key": {
                            "type": "string",
                            "description": (
                                "Target musical key in Camelot notation (e.g. 8A, 11B)."
                                " Set this for harmonic mixing suggestions."
                                " Results are scored against this value."
                            ),
                        },
                        "target_genre": {
                            "type": "string",
                            "description": (
                                "Target genre — set this to the desired genre,"
                                " especially when different from the current profile."
                                " Results are scored against this value."
                            ),
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Brief explanation of why this query was chosen",
                        },
                    },
                    "required": ["search_query", "reasoning"],
                },
                "minItems": 1,
                "maxItems": 6,
            },
        },
        "required": ["queries"],
    },
}


def build_user_prompt(
    profile: EventProfile,
    dj_prompt: str,
    tracks: list[TrackProfile] | None = None,
    rejected_tracks: list[tuple[str, str]] | None = None,
    currently_playing: tuple[str, str, float | None] | None = None,
) -> str:
    """Build the user message from an event profile, track list, and DJ prompt."""
    parts = [f"DJ's request: {dj_prompt}", "", "Current event profile:"]

    if profile.track_count == 0:
        parts.append("  No tracks accepted yet (empty profile)")
    else:
        parts.append(f"  Tracks analyzed: {profile.track_count}")
        if profile.avg_bpm:
            parts.append(f"  Average BPM: {profile.avg_bpm:.0f}")
        if profile.bpm_range:
            parts.append(f"  BPM range: {profile.bpm_range[0]:.0f}-{profile.bpm_range[1]:.0f}")
        if profile.dominant_keys:
            parts.append(f"  Dominant keys: {', '.join(profile.dominant_keys)}")
        if profile.dominant_genres:
            parts.append(f"  Dominant genres: {', '.join(profile.dominant_genres)}")

    if currently_playing:
        artist, title, bpm = currently_playing
        parts.append("")
        bpm_str = f" ({bpm:.0f} BPM)" if bpm else ""
        parts.append(f"Currently playing: {artist} — {title}{bpm_str}")

    if tracks:
        parts.append("")
        parts.append("Tracks in the set:")
        for t in tracks[:30]:  # Cap at 30 to keep prompt manageable
            line = f"  - {t.artist} — {t.title}"
            meta = []
            if t.bpm:
                meta.append(f"{t.bpm:.0f} BPM")
            if t.key:
                meta.append(t.key)
            if t.genre:
                meta.append(t.genre)
            if meta:
                line += f" ({', '.join(meta)})"
            parts.append(line)

    if rejected_tracks:
        parts.append("")
        parts.append("Rejected tracks (DJ said no to these — avoid similar):")
        for artist, title in rejected_tracks[:15]:  # Cap at 15
            parts.append(f"  - {artist} — {title}")

    return "\n".join(parts)


def _parse_tool_response(response) -> LLMSuggestionResult:  # noqa: ANN001 — kept for back-compat
    """Parse a gateway ``ChatResponse`` (or legacy Anthropic Message) into an
    ``LLMSuggestionResult``.

    Accepts both shapes so existing test fixtures (which mock an Anthropic SDK
    response object directly) keep working without modification.
    """
    from app.services.llm.base import ChatResponse

    raw_text = ""
    queries: list[LLMSuggestionQuery] = []

    # Path 1 — canonical ChatResponse (isinstance, not ducktype, so MagicMocks
    # in legacy tests fall through to path 2 instead of matching here).
    if isinstance(response, ChatResponse):
        if response.text:
            raw_text += response.text
        for tc in response.tool_calls or []:
            if tc.name == SEARCH_QUERIES_TOOL_NAME:
                raw_text += json.dumps(tc.input)
                for q in tc.input.get("queries", []):
                    queries.append(
                        LLMSuggestionQuery(
                            search_query=q["search_query"],
                            target_bpm=q.get("target_bpm"),
                            target_key=q.get("target_key"),
                            target_genre=q.get("target_genre"),
                            reasoning=q.get("reasoning", ""),
                        )
                    )
        return LLMSuggestionResult(queries=queries, raw_response=raw_text, model=response.model)

    # Path 2 — legacy Anthropic SDK Message-like object.
    for block in getattr(response, "content", []) or []:
        btype = getattr(block, "type", None)
        if btype == "text":
            raw_text += getattr(block, "text", "")
        elif btype == "tool_use" and getattr(block, "name", "") == SEARCH_QUERIES_TOOL_NAME:
            raw_text += json.dumps(block.input)
            for q in block.input.get("queries", []):
                queries.append(
                    LLMSuggestionQuery(
                        search_query=q["search_query"],
                        target_bpm=q.get("target_bpm"),
                        target_key=q.get("target_key"),
                        target_genre=q.get("target_genre"),
                        reasoning=q.get("reasoning", ""),
                    )
                )

    return LLMSuggestionResult(
        queries=queries, raw_response=raw_text, model=getattr(response, "model", None)
    )


async def call_llm(
    profile: EventProfile,
    dj_prompt: str,
    max_queries: int = 6,
    tracks: list[TrackProfile] | None = None,
    rejected_tracks: list[tuple[str, str]] | None = None,
    currently_playing: tuple[str, str, float | None] | None = None,
    *,
    db: Session | None = None,
    actor: User | None = None,
) -> LLMSuggestionResult:
    """Generate structured search queries via the LLM gateway.

    Compatibility shim: existing callers pass only the positional args. New
    callers pass ``db`` and ``actor`` so the gateway can route to the DJ's
    connector. When ``db`` is missing we fall back to the legacy env-var path
    so unit tests that mock ``AsyncAnthropic`` directly keep passing.

    Returns at most ``max_queries`` queries.
    """
    user_message = build_user_prompt(
        profile,
        dj_prompt,
        tracks=tracks,
        rejected_tracks=rejected_tracks,
        currently_playing=currently_playing,
    )

    if db is None:
        result = await _legacy_call(user_message)
    else:
        chat_request = ChatRequest(
            messages=[Message(role="user", content=user_message)],
            system=SYSTEM_PROMPT,
            tools=[
                ToolSpec(
                    name=SEARCH_QUERIES_TOOL_NAME,
                    description=SEARCH_QUERIES_TOOL["description"],
                    input_schema=SEARCH_QUERIES_TOOL["input_schema"],
                )
            ],
            force_tool=SEARCH_QUERIES_TOOL_NAME,
            max_tokens=_resolve_max_tokens(),
            temperature=None,
        )
        response = await Gateway.dispatch(db, actor, chat_request, purpose="recommendation")
        result = _parse_tool_response(response)

    if len(result.queries) > max_queries:
        result = LLMSuggestionResult(
            queries=result.queries[:max_queries],
            raw_response=result.raw_response,
            model=result.model,
        )

    logger.info(
        "LLM generated %d search queries for prompt: %s",
        len(result.queries),
        dj_prompt[:80],
    )

    return result


def _resolve_max_tokens() -> int:
    return get_settings().anthropic_max_tokens or 1024


async def _legacy_call(user_message: str) -> LLMSuggestionResult:
    """Direct-Anthropic fallback used when no ``db`` is supplied.

    Kept so the legacy unit tests in ``server/tests/test_llm_client.py`` (which
    patch ``AsyncAnthropic`` directly) still pass without modification.
    """
    settings = get_settings()
    client = AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=settings.anthropic_timeout_seconds,
    )

    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=settings.anthropic_max_tokens,
        system=SYSTEM_PROMPT,
        tools=[SEARCH_QUERIES_TOOL],
        tool_choice={"type": "tool", "name": SEARCH_QUERIES_TOOL_NAME},
        messages=[{"role": "user", "content": user_message}],
    )

    return _parse_tool_response(response)
