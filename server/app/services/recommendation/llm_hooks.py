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

    The gateway routes to the actor DJ's connector (or org default). ``db`` is
    required by ``call_llm`` — the legacy direct-Anthropic env-var path was
    removed in #343 now that the connector system is the source of truth.
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
    """Check if LLM features are available for this actor.

    Mirrors :func:`app.services.llm.gateway._resolve_connector` semantics:

    - A DJ with an active connector of their own is ALWAYS available —
      ``llm_enabled`` does not apply to BYO credentials.
    - Otherwise availability equals the gated org fallback: an active
      org-scoped default connector AND ``llm_enabled`` true.

    Connector-backed only. Without ``db`` no connector can be resolved, so it
    returns ``False`` — the legacy Anthropic env-var fallback was removed in #343.
    """
    if db is None:
        return False

    from app.models.llm_connector import SCOPE_USER, STATUS_ACTIVE, LlmConnector
    from app.services.llm.gateway import _resolve_org_default

    if actor is not None:
        actor_active = (
            db.query(LlmConnector.id)
            .filter(
                LlmConnector.user_id == actor.id,
                LlmConnector.scope == SCOPE_USER,
                LlmConnector.status == STATUS_ACTIVE,
            )
            .first()
        )
        if actor_active is not None:
            return True

    return _resolve_org_default(db) is not None
