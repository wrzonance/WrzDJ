"""LLM client for generating recommendation search queries via Claude Haiku.

Sends the event's musical profile and the DJ's prompt to Claude,
which returns structured search queries (with target BPM/key/genre)
that feed into the existing Tidal/Beatport search pipeline.
"""

import json
import logging

from anthropic import AsyncAnthropic

from app.core.config import get_settings
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

SEARCH_QUERIES_TOOL = {
    "name": "search_queries",
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


def _parse_tool_response(response) -> LLMSuggestionResult:
    """Parse the Claude API response into an LLMSuggestionResult."""
    raw_text = ""
    queries: list[LLMSuggestionQuery] = []

    for block in response.content:
        if block.type == "text":
            raw_text += block.text
        elif block.type == "tool_use" and block.name == "search_queries":
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

    return LLMSuggestionResult(queries=queries, raw_response=raw_text)


async def call_llm(
    profile: EventProfile,
    dj_prompt: str,
    max_queries: int = 6,
    tracks: list[TrackProfile] | None = None,
    rejected_tracks: list[tuple[str, str]] | None = None,
    currently_playing: tuple[str, str, float | None] | None = None,
) -> LLMSuggestionResult:
    """Call Claude Haiku to generate search queries from a DJ prompt.

    Returns an LLMSuggestionResult with 1-max_queries structured queries.
    Raises on API failure (caller should handle).
    """
    settings = get_settings()

    client = AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=settings.anthropic_timeout_seconds,
    )

    user_message = build_user_prompt(
        profile,
        dj_prompt,
        tracks=tracks,
        rejected_tracks=rejected_tracks,
        currently_playing=currently_playing,
    )

    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=settings.anthropic_max_tokens,
        system=SYSTEM_PROMPT,
        tools=[SEARCH_QUERIES_TOOL],
        tool_choice={"type": "tool", "name": "search_queries"},
        messages=[{"role": "user", "content": user_message}],
    )

    result = _parse_tool_response(response)

    # Trim to max_queries
    if len(result.queries) > max_queries:
        result = LLMSuggestionResult(
            queries=result.queries[:max_queries],
            raw_response=result.raw_response,
        )

    logger.info(
        "LLM generated %d search queries for prompt: %s",
        len(result.queries),
        dj_prompt[:80],
    )

    return result


async def raw_messages_create(
    *,
    model: str,
    system: str,
    tools: list[dict] | None,
    tool_choice: dict | None,
    messages: list[dict],
    max_tokens: int,
):
    """Low-level Anthropic messages.create passthrough.

    Exists so the provider-agnostic LLM gateway (``app.services.llm.gateway``)
    can delegate here without importing a provider SDK itself. The ``anthropic``
    import stays confined to this module.
    """
    settings = get_settings()
    client = AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=settings.anthropic_timeout_seconds,
    )
    kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools
    if tool_choice:
        kwargs["tool_choice"] = tool_choice
    return await client.messages.create(**kwargs)
