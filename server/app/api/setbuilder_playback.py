"""Playback history and transport routes for set-builder sets."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db, require_owned_event_id
from app.api.setbuilder_common import get_owned_set_or_404 as _get_owned_or_404
from app.api.setbuilder_pairings import pairings_state
from app.core.rate_limit import limiter
from app.models.event import Event
from app.models.set import Set
from app.models.user import User
from app.schemas.setbuilder import (
    ApplyPairingFeedbackOut,
    PlaybackReportSummary,
    PlaybackSlotOutcomeOut,
    PlayHistoryFeedbackOut,
    TransportCommandIn,
    TransportCommandOut,
    TransportStatusOut,
    UnplannedPlayOut,
)
from app.services.bridge_integration import queue_command
from app.services.now_playing import get_now_playing
from app.services.setbuilder import playhistory_feedback

router = APIRouter()


def _playback_report_out(report: playhistory_feedback.FeedbackReport) -> PlayHistoryFeedbackOut:
    return PlayHistoryFeedbackOut(
        event_id=report.event_id,
        slots=[
            PlaybackSlotOutcomeOut(
                slot_id=s.slot_id,
                position=s.position,
                track_id=s.track_id,
                title=s.title,
                artist=s.artist,
                outcome=s.outcome,
                play_order=s.play_order,
                played_at=s.played_at,
                deck=s.deck,
            )
            for s in report.slots
        ],
        unplanned=[
            UnplannedPlayOut(
                play_order=u.play_order,
                title=u.title,
                artist=u.artist,
                played_at=u.played_at,
                deck=u.deck,
                outcome=u.outcome,
            )
            for u in report.unplanned
        ],
        summary=PlaybackReportSummary(
            total_planned=report.summary.total_planned,
            total_played=report.summary.total_played,
            played=report.summary.played,
            skipped=report.summary.skipped,
            out_of_order=report.summary.out_of_order,
            unplanned=report.summary.unplanned,
        ),
    )


def _require_event_attached(db: Session, set_obj: Set, user: User) -> None:
    if set_obj.event_id is None:
        raise HTTPException(
            status_code=400, detail="Set must be attached to an event for a playback report"
        )
    # The binding is validated when written; re-check at read time as well so a
    # row that predates that validation cannot read through to the event.
    require_owned_event_id(db, set_obj.event_id, user)


@router.get(
    "/sets/{set_id}/playback-report",
    response_model=PlayHistoryFeedbackOut,
    responses={400: {"description": "Set has no attached event."}},
)
@limiter.limit("30/minute")
def get_playback_report(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlayHistoryFeedbackOut:
    """Planned-vs-actual report comparing the set's slots to the event's play history."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    _require_event_attached(db, set_obj, current_user)
    report = playhistory_feedback.build_feedback_report(db, set_obj)
    return _playback_report_out(report)


@router.post(
    "/sets/{set_id}/playback-report/apply-pairings",
    response_model=ApplyPairingFeedbackOut,
    responses={400: {"description": "Set has no attached event."}},
)
@limiter.limit("10/minute")
def apply_playback_pairings(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ApplyPairingFeedbackOut:
    """Feed real consecutive plays into pairing use-counts (explicit DJ action)."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    _require_event_attached(db, set_obj, current_user)
    report = playhistory_feedback.build_feedback_report(db, set_obj)
    bumped = playhistory_feedback.apply_outcomes_to_pairings(db, set_obj, report)
    return ApplyPairingFeedbackOut(bumped=bumped, pairings=pairings_state(db, set_obj))


@router.post("/sets/{set_id}/transport/command", response_model=TransportCommandOut)
@limiter.limit("30/minute")
def queue_transport_command(
    set_id: int,
    payload: TransportCommandIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> TransportCommandOut:
    """Queue a setbuilder playback command for the set's attached event Bridge."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    if set_obj.event_id is None:
        raise HTTPException(status_code=400, detail="Set must be attached to an event for playback")

    event = db.get(Event, set_obj.event_id)
    if event is None or event.created_by_user_id != current_user.id:
        raise HTTPException(status_code=400, detail="Set event is unavailable for playback")

    command_id = queue_command(
        event.code.upper(),
        "setbuilder_transport",
        payload.model_dump(),
    )
    return TransportCommandOut(
        command_id=command_id,
        command_type="setbuilder_transport",
        action=payload.action,
        active_source=payload.source,
    )


@router.get("/sets/{set_id}/transport/status", response_model=TransportStatusOut)
@limiter.limit("60/minute")
def get_transport_status(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> TransportStatusOut:
    """Return Bridge connection/source status for the set's attached event."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    if set_obj.event_id is None:
        return TransportStatusOut(connected=False)

    event = db.get(Event, set_obj.event_id)
    if event is None or event.created_by_user_id != current_user.id:
        return TransportStatusOut(connected=False)

    now_playing = get_now_playing(db, set_obj.event_id)
    if now_playing is None:
        return TransportStatusOut(connected=False)

    return TransportStatusOut(
        connected=now_playing.bridge_connected,
        active_source=now_playing.source,
        device_name=now_playing.bridge_device_name,
        last_seen=now_playing.bridge_last_seen,
    )
