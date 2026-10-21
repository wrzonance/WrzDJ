"""Set construction and AI agent routes."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.api.setbuilder_common import get_owned_set_or_404 as _get_owned_or_404
from app.api.setbuilder_common import transition_scores_out
from app.api.setbuilder_pairings import slots_out
from app.core.rate_limit import limiter
from app.models.user import User
from app.schemas.setbuilder import (
    AgentChatHistoryOut,
    AgentChatIn,
    AgentChatMessageOut,
    AgentChatOut,
    AppliedToolCallOut,
    BuildSetRequest,
    BuildSetResponse,
    CritiqueFlagOut,
    PoolCoverageOut,
    SetCritiqueOut,
    TransitionScoreOut,
)
from app.services.llm.exceptions import NoLlmConfigured
from app.services.setbuilder import coverage as pool_coverage_service
from app.services.setbuilder import pass1_deterministic
from app.services.setbuilder.agent import agent_history, pass2_agent

router = APIRouter()


def _agent_message_out(message) -> AgentChatMessageOut:  # noqa: ANN001
    return AgentChatMessageOut(
        id=message.id,
        role=message.role,
        content=message.content,
        display_summary=message.display_summary,
        tool_calls=[
            AppliedToolCallOut(**tool)
            for tool in agent_history.decode_json_list(message.tool_calls_json)
        ],
        affected_transition_scores=[
            TransitionScoreOut(**score)
            for score in agent_history.decode_json_list(message.affected_transition_scores_json)
        ],
        created_at=message.created_at,
    )


@router.post(
    "/sets/{set_id}/build",
    response_model=BuildSetResponse,
    responses={400: {"description": "Build requires explicit confirmation"}},
)
@limiter.limit("10/minute")
def build_set(
    set_id: int,
    payload: BuildSetRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> BuildSetResponse:
    """Run deterministic pass 1 after explicit user confirmation.

    Coverage of the five required pool→builder fields is computed and returned so
    the build-confirmation dialog can show data completeness and a SOFT,
    overridable warning (#542/#538) — the build itself is never blocked on it."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    if not payload.confirmed:
        raise HTTPException(status_code=400, detail="Build requires explicit confirmation")
    coverage = pool_coverage_service.coverage_for_set(db, set_obj.id)
    result = pass1_deterministic.build_set(db, set_obj)
    db.expire(set_obj, ["slots"])
    return BuildSetResponse(
        slot_count=result.slot_count,
        iterations=result.iterations,
        slots=slots_out(db, set_obj),
        transition_scores=transition_scores_out(result.transition_scores),
        coverage=PoolCoverageOut(**coverage),
    )


@router.post(
    "/sets/{set_id}/critique",
    response_model=SetCritiqueOut,
    responses={400: {"description": "No LLM connector configured for this DJ or the org."}},
)
@limiter.limit("10/minute")
async def critique_set(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetCritiqueOut:
    """Run pass 2 auto-critique through the LLM gateway."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    try:
        critique = await pass2_agent.critique_set(db, current_user, set_obj)
    except NoLlmConfigured:
        raise HTTPException(
            status_code=400,
            detail="No AI connector configured — connect one in Settings → AI.",
        ) from None
    return SetCritiqueOut(
        overall_grade=critique.overall_grade,
        summary=critique.summary,
        flags=[
            CritiqueFlagOut(
                type=f.type,
                slot_position=f.slot_position,
                message=f.message,
            )
            for f in critique.flags
        ],
    )


@router.get("/sets/{set_id}/agent/history", response_model=AgentChatHistoryOut)
@limiter.limit("60/minute")
def get_set_agent_history(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> AgentChatHistoryOut:
    """Load persisted agent sidebar history without dispatching an LLM call."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    session = agent_history.get_or_create_session(db, set_obj.id, current_user.id)
    return AgentChatHistoryOut(
        messages=[_agent_message_out(m) for m in agent_history.list_messages(db, session)],
        context_summary=session.context_summary,
        compacted_through_message_id=session.compacted_through_message_id,
        recent_turn_limit=agent_history.RECENT_CONTEXT_TURN_LIMIT,
    )


@router.post(
    "/sets/{set_id}/agent/chat",
    response_model=AgentChatOut,
    responses={
        400: {"description": "Invalid agent tool call or no LLM connector configured."},
    },
)
@limiter.limit("20/minute")
async def chat_with_set_agent(
    set_id: int,
    payload: AgentChatIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> AgentChatOut:
    """Run one agent chat turn and apply validated tool calls."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    session = agent_history.get_or_create_session(db, set_obj.id, current_user.id, commit=False)
    try:
        result = await pass2_agent.chat_with_agent(
            db,
            current_user,
            set_obj,
            message=payload.message,
            messages=agent_history.context_messages(db, set_obj, session, payload.message),
            commit=False,
        )
    except NoLlmConfigured:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="No AI connector configured — connect one in Settings → AI.",
        ) from None
    except pass2_agent.AgentToolError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    agent_history.append_message(db, session, role="user", content=payload.message, commit=False)
    tool_call_payloads = [
        {
            "id": t.id,
            "name": t.name,
            "args": t.args,
            "rationale": t.rationale,
            "result": t.result,
            "mutating": t.mutating,
            "display_summary": t.display_summary,
        }
        for t in result.tool_calls
    ]
    score_payloads = [
        {
            "slot_id": s.slot_id,
            "position": s.position,
            "score": s.score,
            "warnings": s.warnings,
        }
        for s in result.affected_transition_scores
    ]
    assistant_message = agent_history.append_message(
        db,
        session,
        role="assistant",
        content=result.message,
        display_summary=result.message,
        tool_calls=tool_call_payloads,
        affected_transition_scores=score_payloads,
        commit=False,
    )
    agent_history.compact_if_needed(db, session, commit=False)
    db.commit()
    db.refresh(assistant_message)
    db.expire(set_obj, ["slots"])
    return AgentChatOut(
        message=result.message,
        tool_calls=[
            AppliedToolCallOut(
                id=t.id,
                name=t.name,
                args=t.args,
                rationale=t.rationale,
                result=t.result,
                mutating=t.mutating,
                display_summary=t.display_summary,
            )
            for t in result.tool_calls
        ],
        slots=slots_out(db, set_obj),
        affected_transition_scores=transition_scores_out(result.affected_transition_scores),
        assistant_message=_agent_message_out(assistant_message),
    )
