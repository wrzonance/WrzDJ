"""LLM-powered recommendation hooks.

Workflow:
1. Algorithmic engine builds EventProfile from accepted/played tracks
2. LLM receives profile + DJ's natural language prompt
3. LLM returns JSON: suggested search queries with target BPM/key/genre
4. Queries run through existing search infrastructure (Tidal/Beatport)
5. Results scored by existing algorithm and merged into suggestions list
"""

from dataclasses import dataclass

from app.services.recommendation.scorer import EventProfile, TrackProfile


@dataclass(frozen=True)
class LLMSuggestionQuery:
    """A search query suggested by an LLM."""

    search_query: str  # e.g., "deadmau5 progressive house"
    target_bpm: float | None = None
    target_key: str | None = None
    target_genre: str | None = None
    reasoning: str = ""  # LLM's explanation


@dataclass(frozen=True)
class LLMSuggestionResult:
    """Result from LLM suggestion generation."""

    queries: list[LLMSuggestionQuery]
    raw_response: str  # Full LLM response for debugging
    model: str | None = None  # Provider model that actually produced the response


async def generate_llm_suggestions(
    event_profile: EventProfile,
    prompt: str,
    max_queries: int = 6,
    tracks: list[TrackProfile] | None = None,
    rejected_tracks: list[tuple[str, str]] | None = None,
    currently_playing: tuple[str, str, float | None] | None = None,
    *,
    db=None,
    actor=None,
) -> LLMSuggestionResult:
    """Generate search queries via the LLM gateway.

    The gateway routes to the actor DJ's connector (or org default). Existing
    callers that don't pass ``db``/``actor`` fall through to the legacy
    env-var Anthropic path inside ``call_llm`` — see ``llm_client.py``.
    """
    from app.services.recommendation.llm_client import call_llm

    return await call_llm(
        event_profile,
        prompt,
        max_queries,
        tracks=tracks,
        rejected_tracks=rejected_tracks,
        currently_playing=currently_playing,
        db=db,
        actor=actor,
    )


def is_llm_available(db=None, actor=None) -> bool:
    """Check if LLM recommendations are configured and available.

    Mirrors :func:`app.services.llm.gateway._resolve_connector` semantics so the
    "feature available" signal aligns with whether dispatch will actually
    succeed:

    - If ``actor`` is provided: returns True when the actor owns an active
      connector (matches the per-DJ MRU lookup).
    - Otherwise (no actor or no actor-owned active connector): returns True
      when an active system-default connector is configured.
    - As a last fallback, the legacy ``ANTHROPIC_API_KEY`` env var unlocks
      the feature for callers that still take the env-var path.
    """
    from app.core.config import get_settings

    if db is not None:
        from app.models.llm_connector import STATUS_ACTIVE, LlmConnector
        from app.models.system_settings import SystemSettings
        from app.services.system_settings import get_system_settings

        settings = get_system_settings(db)
        if not settings.llm_enabled:
            return False

        # Per-DJ active connector — matches gateway resolver step 1.
        if actor is not None:
            actor_active = (
                db.query(LlmConnector.id)
                .filter(
                    LlmConnector.user_id == actor.id,
                    LlmConnector.status == STATUS_ACTIVE,
                )
                .first()
            )
            if actor_active is not None:
                return True

        # System default fallback — matches gateway resolver step 2.
        sys_settings = db.query(SystemSettings).first()
        if sys_settings and sys_settings.llm_default_connector_id:
            default = db.get(LlmConnector, sys_settings.llm_default_connector_id)
            if default is not None and default.status == STATUS_ACTIVE:
                return True

        # Final fallback: legacy env var (kept until env-var cleanup ships).
        return bool(get_settings().anthropic_api_key)

    return bool(get_settings().anthropic_api_key)
