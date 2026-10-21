"""LLM-powered recommendation hooks.

Workflow:
1. Algorithmic engine builds EventProfile from accepted/played tracks
2. LLM receives profile + DJ's natural language prompt
3. LLM returns JSON: suggested search queries with target BPM/key/genre
4. Queries run through existing search infrastructure (Tidal/Beatport)
5. Results scored by existing algorithm and merged into suggestions list
"""

from sqlalchemy.orm import Session

from app.models.user import User
from app.services.recommendation.context import RecommendationContext
from app.services.recommendation.llm_types import LLMSuggestionQuery as LLMSuggestionQuery
from app.services.recommendation.llm_types import LLMSuggestionResult


async def generate_llm_suggestions(
    context: RecommendationContext,
    prompt: str,
    max_queries: int = 6,
    *,
    db: Session,
    actor: User | None = None,
) -> LLMSuggestionResult:
    """Generate search queries via the LLM gateway.

    The gateway routes to the actor DJ's connector (or org default). ``db`` is
    required by ``call_llm`` — the legacy direct-Anthropic env-var path was
    removed in #343 now that the connector system is the source of truth.
    """
    from app.services.recommendation.llm_client import call_llm

    return await call_llm(
        context,
        prompt,
        max_queries,
        db=db,
        actor=actor,
    )


def is_llm_available(db: Session | None = None, actor: User | None = None) -> bool:
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
    from app.services.llm.gateway import resolve_org_default_connector

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

    return resolve_org_default_connector(db) is not None
