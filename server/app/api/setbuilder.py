"""WrzDJSet set-CRUD router (Phase 0).

Mounted at /api/setbuilder. Every endpoint requires an active DJ
(get_current_active_user rejects pending users). Sets are owner-private;
missing-or-unowned sets return 404 to avoid leaking existence.
"""

from typing import Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.core.rate_limit import limiter
from app.models.set import Set
from app.models.set_pool import SetPoolTrack
from app.models.track_vibe import (
    TRACK_VIBE_SOURCE_EXPLICIT_EDIT,
    TRACK_VIBE_SOURCE_UPVOTE,
    TrackVibeOverride,
)
from app.models.user import User
from app.schemas.setbuilder import (
    AgentChatHistoryOut,
    AgentChatIn,
    AgentChatMessageOut,
    AgentChatOut,
    AppliedToolCallOut,
    ApplyPairingFeedbackOut,
    ApplyTemplateRequest,
    ApplyTemplateResponse,
    BuilderPlaylistsOut,
    BuildSetRequest,
    BuildSetResponse,
    BuiltinTemplateOut,
    CommunityVibeOut,
    CritiqueFlagOut,
    CurvePointModel,
    CurveTemplateCreate,
    CurveTemplateOut,
    CurveTemplatesResponse,
    ExportFileIn,
    ExportPreflightIn,
    ExportPreflightOut,
    ExportTidalIn,
    ExportTidalOut,
    LlmVibeOut,
    OwnVibeOut,
    PairingCreate,
    PairingOut,
    PairingsState,
    PairingUpdate,
    PlaybackReportSummary,
    PlaybackSlotOutcomeOut,
    PlayHistoryFeedbackOut,
    PoolCoverageOut,
    PoolEnrichmentSummary,
    PoolImportEventIn,
    PoolImportManualIn,
    PoolImportPlaylistIn,
    PoolImportResult,
    PoolImportUrlIn,
    PoolMutationResult,
    PoolRemoveTracksIn,
    PoolSourceOut,
    PoolState,
    PoolTrackOut,
    PoolUrlPreview,
    PoolVibeOverrideIn,
    PoolVibesState,
    ResolvedVibeOut,
    SetCreate,
    SetCritiqueOut,
    SetDetail,
    SetDocumentSnapshot,
    SetRename,
    SetSummary,
    SetTargetUpdate,
    SlotOrderRequest,
    SlotOut,
    SlotTargetOut,
    SlotTargetUpdate,
    TasteProfileMoodOut,
    TasteProfileOut,
    TemplateWindowOut,
    TrackVibeStateOut,
    TransitionScoreOut,
    TransportCommandIn,
    TransportCommandOut,
    TransportStatusOut,
    UnplannedPlayOut,
    UnresolvedTrackOut,
    UnresolvedTracksError,
    VibeEnrichmentResult,
    VibeWindowModel,
    VibeWindowsPut,
    VibeWindowsResponse,
)
from app.services.bridge_integration import queue_command
from app.services.llm.exceptions import NoLlmConfigured
from app.services.now_playing import get_now_playing
from app.services.setbuilder import (
    agent_history,
    curve,
    document_snapshot,
    export_common,
    export_files,
    export_tidal,
    pairings,
    pass1_deterministic,
    pass2_agent,
    playhistory_feedback,
    pool,
    reorder,
    set_service,
    taste_profile,
    vibe_enrichment,
    vibe_resolver,
)
from app.services.setbuilder import (
    coverage as pool_coverage_service,
)
from app.services.setbuilder.playlist_url import InvalidPlaylistUrl, parse_public_playlist_url

router = APIRouter()


def _get_owned_or_404(db: Session, set_id: int, user: User) -> Set:
    set_obj = set_service.get_owned_set(db, set_id, user.id)
    if set_obj is None:
        raise HTTPException(status_code=404, detail="Set not found")
    return set_obj


def _transition_scores_out(
    scores: list[pass1_deterministic.TransitionScore],
) -> list[TransitionScoreOut]:
    return [
        TransitionScoreOut(
            slot_id=s.slot_id,
            position=s.position,
            score=s.score,
            warnings=s.warnings,
        )
        for s in scores
    ]


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


def _taste_profile_out(profile: taste_profile.TasteProfile) -> TasteProfileOut:
    return TasteProfileOut(
        sample_count=profile.sample_count,
        min_samples=profile.min_samples,
        active=profile.active,
        average_energy_delta=profile.average_energy_delta,
        energy_adjustment=profile.energy_adjustment,
        top_moods=[
            TasteProfileMoodOut(mood=mood.mood, count=mood.count) for mood in profile.top_moods
        ],
        summary=profile.summary,
        reset_at=profile.reset_at,
    )


@router.get("/taste-profile", response_model=TasteProfileOut)
@limiter.limit("30/minute")
def get_taste_profile(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> TasteProfileOut:
    """Return the current DJ's learned SetBuilder taste profile."""
    return _taste_profile_out(taste_profile.build_taste_profile(db, current_user.id))


@router.post("/taste-profile/reset", response_model=TasteProfileOut)
@limiter.limit("10/minute")
def reset_taste_profile(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> TasteProfileOut:
    """Reset learned profile training history without deleting override rows."""
    return _taste_profile_out(taste_profile.reset_taste_profile(db, current_user.id))


@router.post("/sets", response_model=SetDetail, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
def create_set(
    payload: SetCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetDetail:
    """Create a new empty set owned by the current DJ."""
    set_obj = set_service.create_set(
        db, owner_id=current_user.id, name=payload.name, event_id=payload.event_id
    )
    return SetDetail.model_validate(set_obj)


@router.get("/sets", response_model=list[SetSummary])
@limiter.limit("60/minute")
def list_sets(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[SetSummary]:
    """List the current DJ's sets, newest first."""
    return [SetSummary.model_validate(s) for s in set_service.list_sets(db, current_user.id)]


@router.get("/sets/{set_id}", response_model=SetDetail)
@limiter.limit("60/minute")
def get_set(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetDetail:
    """Get one of the current DJ's sets, or 404."""
    return SetDetail.model_validate(_get_owned_or_404(db, set_id, current_user))


@router.patch("/sets/{set_id}", response_model=SetDetail)
@limiter.limit("30/minute")
def rename_set(
    set_id: int,
    payload: SetRename,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetDetail:
    """Rename one of the current DJ's sets, or 404."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    return SetDetail.model_validate(set_service.rename_set(db, set_obj, payload.name))


@router.put("/sets/{set_id}/target", response_model=SetDetail)
@limiter.limit("30/minute")
def update_set_target(
    set_id: int,
    payload: SetTargetUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetDetail:
    """Update set-length target + average transition overlap."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    return SetDetail.model_validate(
        set_service.update_target_settings(
            db,
            set_obj,
            target_duration_sec=payload.target_duration_sec,
            avg_transition_overlap_sec=payload.avg_transition_overlap_sec,
        )
    )


@router.delete("/sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
def delete_set(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Delete one of the current DJ's sets, or 404."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    set_service.delete_set(db, set_obj)


# ---------------------------------------------------------------------------
# Energy curve editor (#389) — templates, slot targets, vibe windows
# ---------------------------------------------------------------------------


def _builtin_templates_out() -> list[BuiltinTemplateOut]:
    return [
        BuiltinTemplateOut(name=name, points=[CurvePointModel(**p) for p in points])
        for name, points in curve.BUILTIN_TEMPLATES.items()
    ]


def _template_out(tpl) -> CurveTemplateOut:
    return CurveTemplateOut(
        id=tpl.id,
        name=tpl.name,
        points=[CurvePointModel(**p) for p in curve.template_points(tpl)],
        updated_at=tpl.updated_at,
    )


def _get_owned_template_or_404(db: Session, template_id: int, user: User):
    tpl = curve.get_owned_template(db, template_id, user.id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return tpl


def _pairing_out(view: pairings.PairingView) -> PairingOut:
    p = view.pairing
    return PairingOut(
        id=p.id,
        set_id=p.set_id,
        from_track_id=p.from_track_id,
        into_track_id=p.into_track_id,
        cue_in_sec=p.cue_in_sec,
        note=p.note,
        tags=pairings.tags_for_pairing(p),
        use_count=p.use_count,
        from_track=PoolTrackOut.model_validate(view.from_track) if view.from_track else None,
        into_track=PoolTrackOut.model_validate(view.into_track) if view.into_track else None,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _pairings_state(db: Session, set_obj: Set, query: str | None = None) -> PairingsState:
    views = pairings.list_pairings(db, set_obj, query)
    return PairingsState(count=len(views), pairings=[_pairing_out(v) for v in views])


def _slots_out(db: Session, set_obj: Set) -> list[SlotOut]:
    """Ordered slots with pool metadata and saved-pairing seam markers."""
    ordered = sorted(set_obj.slots, key=lambda s: s.position)
    track_ids = [s.track_id for s in ordered if s.track_id]
    pool_track_ids = [
        int(s.track_id.removeprefix("pool:"))
        for s in ordered
        if s.track_id
        and s.track_id.startswith("pool:")
        and s.track_id.removeprefix("pool:").isdigit()
    ]
    tracks_by_id: dict[str, SetPoolTrack] = {}
    if track_ids or pool_track_ids:
        query = db.query(SetPoolTrack).filter(SetPoolTrack.set_id == set_obj.id)
        filters = []
        if track_ids:
            filters.append(SetPoolTrack.track_id.in_(track_ids))
        if pool_track_ids:
            filters.append(SetPoolTrack.id.in_(pool_track_ids))
        tracks = query.filter(or_(*filters)).all()
        for track in tracks:
            if track.track_id:
                tracks_by_id[track.track_id] = track
            tracks_by_id[f"pool:{track.id}"] = track
    by_transition = {(p.from_track_id, p.into_track_id): p.id for p in set_obj.pairings}
    out: list[SlotOut] = []
    for idx, slot in enumerate(ordered):
        track = tracks_by_id.get(slot.track_id or "")
        next_slot = ordered[idx + 1] if idx + 1 < len(ordered) else None
        pairing_id = None
        if slot.track_id and next_slot and next_slot.track_id:
            pairing_id = by_transition.get((slot.track_id, next_slot.track_id))
        out.append(
            SlotOut(
                id=slot.id,
                position=slot.position,
                track_id=slot.track_id,
                locked=slot.locked,
                target_energy=slot.target_energy,
                notes=slot.notes,
                transition_score=slot.transition_score,
                transition_warnings=slot.transition_warnings,
                pool_track_id=track.id if track else None,
                title=track.title if track else None,
                artist=track.artist if track else None,
                bpm=track.bpm if track else None,
                key=track.key if track else None,
                camelot=track.camelot if track else None,
                energy=track.energy if track else None,
                duration_sec=track.duration_sec if track else None,
                next_pairing_id=pairing_id,
                next_is_dj_pairing=pairing_id is not None,
            )
        )
    return out


@router.get("/curve-templates", response_model=CurveTemplatesResponse)
@limiter.limit("60/minute")
def list_curve_templates(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> CurveTemplatesResponse:
    """Built-in templates plus the current DJ's saved templates."""
    return CurveTemplatesResponse(
        builtin=_builtin_templates_out(),
        user=[_template_out(t) for t in curve.list_templates(db, current_user.id)],
    )


@router.post(
    "/curve-templates", response_model=CurveTemplateOut, status_code=status.HTTP_201_CREATED
)
@limiter.limit("30/minute")
def create_curve_template(
    payload: CurveTemplateCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> CurveTemplateOut:
    """Save a new per-DJ curve template."""
    points = [p.model_dump(exclude_none=True) for p in payload.points]
    return _template_out(curve.create_template(db, current_user.id, payload.name, points))


@router.put("/curve-templates/{template_id}", response_model=CurveTemplateOut)
@limiter.limit("30/minute")
def update_curve_template(
    template_id: int,
    payload: CurveTemplateCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> CurveTemplateOut:
    """Overwrite one of the current DJ's templates, or 404."""
    tpl = _get_owned_template_or_404(db, template_id, current_user)
    points = [p.model_dump(exclude_none=True) for p in payload.points]
    return _template_out(curve.update_template(db, tpl, payload.name, points))


@router.delete("/curve-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
def delete_curve_template(
    template_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Delete one of the current DJ's templates, or 404."""
    tpl = _get_owned_template_or_404(db, template_id, current_user)
    curve.delete_template(db, tpl)


@router.get("/sets/{set_id}/slots", response_model=list[SlotOut])
@limiter.limit("60/minute")
def list_set_slots(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[SlotOut]:
    """Ordered timeline slots for one of the current DJ's sets."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    return _slots_out(db, set_obj)


@router.get("/sets/{set_id}/pairings", response_model=PairingsState)
@limiter.limit("60/minute")
def list_set_pairings(
    set_id: int,
    request: Request,
    query: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PairingsState:
    """Searchable pairings overlay state for one of the current DJ's sets."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    return _pairings_state(db, set_obj, query)


@router.post(
    "/sets/{set_id}/pairings",
    response_model=PairingOut,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_200_OK: {"model": PairingOut}},
)
@limiter.limit("30/minute")
def create_set_pairing(
    set_id: int,
    payload: PairingCreate,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PairingOut:
    """Create or update a DJ-curated transition pairing."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    try:
        pairing, created = pairings.upsert_pairing(
            db,
            set_obj,
            from_track_id=payload.from_track_id,
            into_track_id=payload.into_track_id,
            cue_in_sec=payload.cue_in_sec,
            note=payload.note,
            tags=payload.tags,
            increment_use_count=payload.increment_use_count,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not created:
        response.status_code = status.HTTP_200_OK
    return _pairing_out(pairings.pairing_view(db, set_obj, pairing))


@router.patch("/sets/{set_id}/pairings/{pairing_id}", response_model=PairingOut)
@limiter.limit("30/minute")
def update_set_pairing(
    set_id: int,
    pairing_id: int,
    payload: PairingUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PairingOut:
    """Inline-edit note, tags, and cue-in for a pairing."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    pairing = pairings.get_pairing(db, set_obj, pairing_id)
    if pairing is None:
        raise HTTPException(status_code=404, detail="Pairing not found")
    fields = payload.model_fields_set
    tags = (
        payload.tags
        if "tags" in fields and payload.tags is not None
        else pairings.tags_for_pairing(pairing)
    )
    updated = pairings.update_pairing(
        db,
        pairing,
        cue_in_sec=payload.cue_in_sec if "cue_in_sec" in fields else pairing.cue_in_sec,
        note=payload.note if "note" in fields else pairing.note,
        tags=tags,
    )
    return _pairing_out(pairings.pairing_view(db, set_obj, updated))


@router.delete("/sets/{set_id}/pairings/{pairing_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
def delete_set_pairing(
    set_id: int,
    pairing_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Delete a pairing from one of the current DJ's sets."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    pairing = pairings.get_pairing(db, set_obj, pairing_id)
    if pairing is None:
        raise HTTPException(status_code=404, detail="Pairing not found")
    pairings.delete_pairing(db, pairing)


# ---------------------------------------------------------------------------
# Play-history feedback loop (issue #403) — derive-on-read planned-vs-actual.
# Read-only on play_history AND requests; the only write is SetPairing.use_count
# via the explicit apply-pairings action.


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


def _require_event_attached(set_obj: Set) -> None:
    if set_obj.event_id is None:
        raise HTTPException(
            status_code=400, detail="Set must be attached to an event for a playback report"
        )


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
    _require_event_attached(set_obj)
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
    _require_event_attached(set_obj)
    report = playhistory_feedback.build_feedback_report(db, set_obj)
    bumped = playhistory_feedback.apply_outcomes_to_pairings(db, set_obj, report)
    return ApplyPairingFeedbackOut(bumped=bumped, pairings=_pairings_state(db, set_obj))


@router.patch("/sets/{set_id}/slots/{slot_id}/target", response_model=SlotTargetOut)
@limiter.limit("60/minute")
def update_slot_target(
    set_id: int,
    slot_id: int,
    payload: SlotTargetUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SlotTargetOut:
    """Set (or clear with null) a slot's energy target."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    slot = next((s for s in set_obj.slots if s.id == slot_id), None)
    if slot is None:
        raise HTTPException(status_code=404, detail="Slot not found")
    slot = curve.set_slot_target(db, slot, payload.target_energy)
    return SlotTargetOut(slot_id=slot.id, target_energy=slot.target_energy)


@router.put(
    "/sets/{set_id}/slots/order",
    response_model=list[TransitionScoreOut],
    responses={
        400: {"description": "Invalid reorder (not a permutation, or would move a locked slot)"}
    },
)
@limiter.limit("30/minute")
def reorder_slots(
    set_id: int,
    payload: SlotOrderRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[TransitionScoreOut]:
    """Reassign the set's slot order by hand and recompute transition scores (#437)."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    try:
        scores = reorder.apply_slot_order(db, set_obj, payload.slot_ids)
    except reorder.ReorderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _transition_scores_out(scores)


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
        slots=_slots_out(db, set_obj),
        transition_scores=_transition_scores_out(result.transition_scores),
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
        slots=_slots_out(db, set_obj),
        affected_transition_scores=_transition_scores_out(result.affected_transition_scores),
        assistant_message=_agent_message_out(assistant_message),
    )


@router.post("/sets/{set_id}/curve/apply-template", response_model=ApplyTemplateResponse)
@limiter.limit("30/minute")
def apply_curve_template(
    set_id: int,
    payload: ApplyTemplateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ApplyTemplateResponse:
    """Re-target every slot from a built-in or saved template shape."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    if payload.builtin is not None:
        points = curve.BUILTIN_TEMPLATES.get(payload.builtin)
        if points is None:
            raise HTTPException(status_code=404, detail="Template not found")
    else:
        tpl = _get_owned_template_or_404(db, payload.template_id, current_user)
        points = curve.template_points(tpl)
    try:
        applied = curve.apply_points_to_slots(db, set_obj, points, payload.slot_midpoints)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApplyTemplateResponse(
        targets=[SlotTargetOut(slot_id=sid, target_energy=t) for sid, t in applied],
        windows=[TemplateWindowOut(**w) for w in curve.windows_from_points(points)],
    )


@router.get("/sets/{set_id}/vibe-windows", response_model=VibeWindowsResponse)
@limiter.limit("60/minute")
def get_vibe_windows(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> VibeWindowsResponse:
    """The set's stored vibe windows."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    windows = curve.get_vibe_windows(db, set_obj.id)
    return VibeWindowsResponse(windows=[VibeWindowModel(**w) for w in windows])


@router.put("/sets/{set_id}/vibe-windows", response_model=VibeWindowsResponse)
@limiter.limit("30/minute")
def put_vibe_windows(
    set_id: int,
    payload: VibeWindowsPut,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> VibeWindowsResponse:
    """Replace-all update of the set's vibe windows."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    stored = curve.replace_vibe_windows(db, set_obj, [w.model_dump() for w in payload.windows])
    return VibeWindowsResponse(windows=[VibeWindowModel(**w) for w in stored])


# ---------------------------------------------------------------------------
# Transport (issue #393) — queue playback commands for the attached event's Bridge.


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

    from app.models.event import Event

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

    from app.models.event import Event

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


# ---------------------------------------------------------------------------
# Document snapshots (issue #395) — undo/redo + autosave restore surface.


@router.get(
    "/sets/{set_id}/document",
    response_model=SetDocumentSnapshot,
    responses={404: {"description": "Set not found or not accessible"}},
)
@limiter.limit("60/minute")
def get_document_snapshot(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetDocumentSnapshot:
    """Full restorable builder document snapshot for one of the current DJ's sets."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    return document_snapshot.build_snapshot(set_obj)


@router.put(
    "/sets/{set_id}/document",
    response_model=SetDocumentSnapshot,
    responses={404: {"description": "Set not found or not accessible"}},
)
@limiter.limit("30/minute")
def put_document_snapshot(
    set_id: int,
    payload: SetDocumentSnapshot,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetDocumentSnapshot:
    """Replace the restorable builder document with a prior snapshot."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    return document_snapshot.restore_snapshot(db, set_obj, payload)


# ---------------------------------------------------------------------------
# Pool (issue #388) — candidate-track surface with per-source import/removal.
# All endpoints are owner-scoped via _get_owned_or_404.


def _pool_state(db: Session, set_id: int) -> PoolState:
    sources, tracks = pool.get_pool(db, set_id)
    return PoolState(
        sources=[PoolSourceOut.model_validate(s) for s in sources],
        tracks=[PoolTrackOut.model_validate(t) for t in tracks],
        runtime_sec=pool.pool_runtime_sec(db, set_id),
        enrichment=_pool_enrichment_summary(tracks),
    )


def _pool_enrichment_summary(tracks: list[SetPoolTrack]) -> PoolEnrichmentSummary:
    enriched = sum(1 for track in tracks if track.enrichment_status == pool.POOL_ENRICHED)
    failed = sum(1 for track in tracks if track.enrichment_status == pool.POOL_ENRICH_FAILED)
    pending = sum(1 for track in tracks if track.enrichment_status == pool.POOL_ENRICH_PENDING)
    return PoolEnrichmentSummary(
        total=len(tracks),
        enriched=enriched,
        failed=failed,
        pending=pending,
        in_progress=pending > 0,
    )


def _import_result(db: Session, set_id: int, source, added: int, deduped: int) -> PoolImportResult:
    return PoolImportResult(
        added=added,
        deduped=deduped,
        source=PoolSourceOut.model_validate(source),
        pool=_pool_state(db, set_id),
    )


def _queue_pool_enrichment(
    db: Session, background_tasks: BackgroundTasks, set_id: int, source_id: int
) -> None:
    pending_ids = pool.pending_enrichment_track_ids(db, set_id, source_id=source_id)
    if pending_ids:
        background_tasks.add_task(pool.enrich_pool_tracks, set_id, pending_ids)


@router.get("/sets/{set_id}/pool", response_model=PoolState)
@limiter.limit("60/minute")
def get_pool_state(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolState:
    """Full pool snapshot (sources + tracks) for one of the DJ's sets."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    return _pool_state(db, set_obj.id)


@router.get("/playlists", response_model=BuilderPlaylistsOut)
@limiter.limit("20/minute")
def list_builder_playlists(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> BuilderPlaylistsOut:
    """Connected-service playlists for the import modal pickers."""
    from app.schemas.recommendation import PlaylistInfo

    tidal_connected = bool(current_user.tidal_access_token)
    beatport_connected = bool(current_user.beatport_access_token)
    tidal_playlists: list[PlaylistInfo] = []
    beatport_playlists: list[PlaylistInfo] = []

    if tidal_connected:
        from app.services.tidal import list_user_playlists as tidal_list

        tidal_playlists = [PlaylistInfo(**vars(p)) for p in tidal_list(db, current_user)]
    if beatport_connected:
        from app.services.beatport import list_user_playlists as bp_list

        beatport_playlists = [PlaylistInfo(**vars(p)) for p in bp_list(db, current_user)]

    return BuilderPlaylistsOut(
        tidal_connected=tidal_connected,
        beatport_connected=beatport_connected,
        tidal=tidal_playlists,
        beatport=beatport_playlists,
    )


@router.post("/sets/{set_id}/pool/import/event", response_model=PoolImportResult)
@limiter.limit("10/minute")
def import_pool_event(
    set_id: int,
    payload: PoolImportEventIn,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolImportResult:
    """Import a DJ-owned event's non-rejected requests into the pool."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    result = pool.candidates_from_event(db, current_user, payload.event_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Event not found")
    event, candidates = result
    source = pool.get_or_create_source(
        db,
        set_obj,
        kind="event",
        external_ref=str(event.id),
        label=event.name,
        meta="WrzDJ event requests",
    )
    candidates = pool.hydrate_candidates_from_store(
        db, candidates, user=current_user, enrich_missing=False
    )
    added, deduped = pool.import_candidates(db, set_obj, source, candidates)
    _queue_pool_enrichment(db, background_tasks, set_obj.id, source.id)
    return _import_result(db, set_obj.id, source, added, deduped)


@router.post("/sets/{set_id}/pool/import/tidal", response_model=PoolImportResult)
@limiter.limit("10/minute")
def import_pool_tidal(
    set_id: int,
    payload: PoolImportPlaylistIn,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolImportResult:
    """Import a connected-account Tidal playlist into the pool."""
    from app.services.tidal import TidalFetchError

    set_obj = _get_owned_or_404(db, set_id, current_user)
    try:
        candidates = pool.candidates_from_tidal(db, current_user, payload.playlist_id)
    except TidalFetchError:
        raise HTTPException(status_code=502, detail="Couldn't fetch that Tidal playlist") from None
    source = pool.get_or_create_source(
        db,
        set_obj,
        kind="tidal",
        external_ref=payload.playlist_id,
        label=payload.label or "Tidal playlist",
        meta="Tidal playlist",
    )
    candidates = pool.hydrate_candidates_from_store(
        db, candidates, user=current_user, enrich_missing=False
    )
    added, deduped = pool.import_candidates(db, set_obj, source, candidates)
    _queue_pool_enrichment(db, background_tasks, set_obj.id, source.id)
    return _import_result(db, set_obj.id, source, added, deduped)


@router.post("/sets/{set_id}/pool/import/beatport", response_model=PoolImportResult)
@limiter.limit("10/minute")
def import_pool_beatport(
    set_id: int,
    payload: PoolImportPlaylistIn,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolImportResult:
    """Import a connected-account Beatport playlist into the pool."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    # beatport.get_playlist_tracks returns [] on fetch failure (existing semantics)
    candidates = pool.candidates_from_beatport(db, current_user, payload.playlist_id)
    source = pool.get_or_create_source(
        db,
        set_obj,
        kind="beatport",
        external_ref=payload.playlist_id,
        label=payload.label or "Beatport playlist",
        meta="Beatport playlist",
    )
    candidates = pool.hydrate_candidates_from_store(
        db, candidates, user=current_user, enrich_missing=False
    )
    added, deduped = pool.import_candidates(db, set_obj, source, candidates)
    _queue_pool_enrichment(db, background_tasks, set_obj.id, source.id)
    return _import_result(db, set_obj.id, source, added, deduped)


@router.post("/sets/{set_id}/pool/url-preview", response_model=PoolUrlPreview)
@limiter.limit("10/minute")
def preview_pool_url(
    set_id: int,
    payload: PoolImportUrlIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolUrlPreview:
    """Validate a public playlist URL and return the preview card payload."""
    _get_owned_or_404(db, set_id, current_user)
    try:
        parsed = parse_public_playlist_url(payload.url)
    except InvalidPlaylistUrl as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    if not parsed.supported:
        return PoolUrlPreview(provider=parsed.provider, supported=False, message=parsed.message)
    try:
        meta = pool.preview_public_playlist(db, current_user, parsed.provider, parsed.playlist_id)
    except pool.PoolImportError as e:
        raise HTTPException(status_code=502, detail=str(e)) from None
    return PoolUrlPreview(provider=parsed.provider, supported=True, **meta)


@router.post("/sets/{set_id}/pool/import/url", response_model=PoolImportResult)
@limiter.limit("10/minute")
def import_pool_url(
    set_id: int,
    payload: PoolImportUrlIn,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolImportResult:
    """Import a validated public playlist URL into the pool."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    try:
        parsed = parse_public_playlist_url(payload.url)
    except InvalidPlaylistUrl as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    if not parsed.supported:
        raise HTTPException(status_code=422, detail=parsed.message)
    try:
        name, candidates = pool.candidates_from_public_url(
            db, current_user, parsed.provider, parsed.playlist_id
        )
    except pool.PoolImportError as e:
        raise HTTPException(status_code=502, detail=str(e)) from None
    source = pool.get_or_create_source(
        db,
        set_obj,
        kind="public_url",
        external_ref=f"{parsed.provider}:{parsed.playlist_id}",
        label=name,
        meta=f"Public {parsed.provider} playlist",
    )
    candidates = pool.hydrate_candidates_from_store(
        db, candidates, user=current_user, enrich_missing=False
    )
    added, deduped = pool.import_candidates(db, set_obj, source, candidates)
    _queue_pool_enrichment(db, background_tasks, set_obj.id, source.id)
    return _import_result(db, set_obj.id, source, added, deduped)


@router.post("/sets/{set_id}/pool/import/manual", response_model=PoolImportResult)
@limiter.limit("30/minute")
def import_pool_manual(
    set_id: int,
    payload: PoolImportManualIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolImportResult:
    """Add a single manually-searched track to the pool."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    candidate = pool.candidate_from_manual(
        title=payload.title,
        artist=payload.artist,
        album=payload.album,
        genre=payload.genre,
        bpm=payload.bpm,
        key=payload.key,
        isrc=payload.isrc,
        duration_sec=payload.duration_sec,
        artwork_url=payload.artwork_url,
        source_service=payload.source_service,
        source_track_id=payload.source_track_id,
    )
    source = pool.get_or_create_source(
        db, set_obj, kind="manual", external_ref=None, label="Manual", meta="Single-track search"
    )
    candidates = pool.hydrate_candidates_from_store(db, [candidate], user=current_user)
    added, deduped = pool.import_candidates(db, set_obj, source, candidates)
    return _import_result(db, set_obj.id, source, added, deduped)


@router.post("/sets/{set_id}/pool/tracks/remove", response_model=PoolMutationResult)
@limiter.limit("30/minute")
def remove_pool_tracks(
    set_id: int,
    payload: PoolRemoveTracksIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolMutationResult:
    """Remove pool tracks by id (per-track context menu + multi-select)."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    removed = pool.remove_tracks(db, set_obj, payload.track_ids)
    return PoolMutationResult(removed=removed, pool=_pool_state(db, set_obj.id))


@router.delete("/sets/{set_id}/pool/sources/{source_id}", response_model=PoolMutationResult)
@limiter.limit("30/minute")
def remove_pool_source(
    set_id: int,
    source_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolMutationResult:
    """Remove an import source and exactly its tracks."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    source = pool.get_owned_source(db, set_obj, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    removed = pool.remove_source(db, set_obj, source)
    return PoolMutationResult(removed=removed, pool=_pool_state(db, set_obj.id))


# ---------------------------------------------------------------------------
# Track vibes (issue #391) — read-only three-tier state + LLM enrichment


def _pool_vibes_state(db: Session, actor: User, set_obj: Set) -> PoolVibesState:
    states = vibe_resolver.build_pool_vibe_states(db, actor, set_obj)
    out = []
    for s in states:
        llm_out = None
        if s.llm is not None:
            llm_out = LlmVibeOut(
                energy=s.llm.energy,
                mood=s.llm.mood,
                era=s.llm.era,
                sing_along=s.llm.sing_along,
                dance_floor=s.llm.dance_floor,
                transitional_role=s.llm.transitional_role,
                confidence=s.llm.confidence,
                low_confidence=vibe_resolver.is_low_confidence(s.llm),
                llm_provider=s.llm.llm_provider,
                llm_model=s.llm.llm_model,
            )
        out.append(
            TrackVibeStateOut(
                pool_track_id=s.pool_track_id,
                vibe_key=s.vibe_key,
                own=OwnVibeOut(energy=s.own.energy, mood=s.own.mood) if s.own else None,
                community=(
                    CommunityVibeOut(
                        energy=s.community.energy,
                        mood=s.community.mood,
                        sample_size=s.community.sample_size,
                    )
                    if s.community
                    else None
                ),
                llm=llm_out,
                resolved=ResolvedVibeOut(
                    energy=s.resolved.energy,
                    energy_source=s.resolved.energy_source,
                    mood=s.resolved.mood,
                    mood_source=s.resolved.mood_source,
                ),
            )
        )
    return PoolVibesState(tracks=out)


def _pool_vibe_state_for_track(
    db: Session,
    actor: User,
    set_obj: Set,
    pool_track_id: int,
) -> vibe_resolver.TrackVibeState:
    state = vibe_resolver.build_pool_vibe_state(db, actor, set_obj, pool_track_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Pool track not found")
    return state


def _agree_values(state: vibe_resolver.TrackVibeState) -> tuple[int | None, str | None]:
    energy = (
        state.community.energy
        if state.community and state.community.energy is not None
        else state.llm.energy
        if state.llm
        else None
    )
    mood = (
        state.community.mood
        if state.community and state.community.mood is not None
        else state.llm.mood
        if state.llm
        else None
    )
    if energy is None and mood is None:
        raise HTTPException(status_code=400, detail="No vibe available to agree with")
    return energy, mood


def _overridden_from_vibe_id(state: vibe_resolver.TrackVibeState) -> int | None:
    if state.llm is None:
        return None
    if "llm" in {state.resolved.energy_source, state.resolved.mood_source}:
        return state.llm.id
    return None


def _write_vibe_override(
    db: Session,
    actor: User,
    state: vibe_resolver.TrackVibeState,
    *,
    energy: int | None,
    mood: str | None,
    source: str,
    energy_was: int | None = None,
    mood_was: str | None = None,
    overridden_from_vibe_id: int | None = None,
) -> TrackVibeOverride:
    row = TrackVibeOverride(
        track_id=state.vibe_key,
        user_id=actor.id,
        energy_override=energy,
        mood_override=mood,
        overridden_from_vibe_id=overridden_from_vibe_id,
        energy_was=energy_was,
        mood_was=mood_was,
        source=source,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/sets/{set_id}/pool/vibes", response_model=PoolVibesState)
@limiter.limit("60/minute")
def get_pool_vibes(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolVibesState:
    """Three-tier vibe state (own / community / LLM) for the set's pool."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    return _pool_vibes_state(db, current_user, set_obj)


@router.post(
    "/sets/{set_id}/pool/vibes/{pool_track_id}/agree",
    response_model=PoolVibesState,
    responses={400: {"description": "No non-own vibe signal available for this pool track."}},
)
@limiter.limit("30/minute")
def agree_pool_vibe(
    set_id: int,
    pool_track_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolVibesState:
    """Upvote the best non-own vibe signal for one pool track without creating an own tier."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    state = _pool_vibe_state_for_track(db, current_user, set_obj, pool_track_id)
    energy, mood = _agree_values(state)
    _write_vibe_override(
        db,
        current_user,
        state,
        energy=energy,
        mood=mood,
        source=TRACK_VIBE_SOURCE_UPVOTE,
    )
    return _pool_vibes_state(db, current_user, set_obj)


@router.patch("/sets/{set_id}/pool/vibes/{pool_track_id}/override", response_model=PoolVibesState)
@limiter.limit("30/minute")
def override_pool_vibe(
    set_id: int,
    pool_track_id: int,
    payload: PoolVibeOverrideIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolVibesState:
    """Write an explicit DJ vibe edit, preserving omitted fields from their latest vote."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    state = _pool_vibe_state_for_track(db, current_user, set_obj, pool_track_id)
    latest = vibe_resolver.latest_override_row(db, current_user.id, state.vibe_key)
    energy = (
        payload.energy
        if "energy" in payload.model_fields_set
        else latest.energy_override
        if latest
        else None
    )
    mood = (
        payload.mood
        if "mood" in payload.model_fields_set
        else latest.mood_override
        if latest
        else None
    )
    _write_vibe_override(
        db,
        current_user,
        state,
        energy=energy,
        mood=mood,
        source=TRACK_VIBE_SOURCE_EXPLICIT_EDIT,
        energy_was=state.resolved.energy,
        mood_was=state.resolved.mood,
        overridden_from_vibe_id=_overridden_from_vibe_id(state),
    )
    return _pool_vibes_state(db, current_user, set_obj)


@router.post(
    "/sets/{set_id}/pool/vibes/enrich",
    response_model=VibeEnrichmentResult,
    responses={
        400: {"description": "No LLM connector configured for this DJ or the org."},
    },
)
@limiter.limit("5/minute")
async def enrich_pool_vibes(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> VibeEnrichmentResult:
    """Batch-enrich uncached pool tracks via the LLM gateway (20 tracks/call)."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    try:
        stats = await vibe_enrichment.enrich_pool_vibes(db, current_user, set_obj)
    except NoLlmConfigured:
        raise HTTPException(
            status_code=400,
            detail="No AI connector configured — connect one in Settings → AI.",
        ) from None
    return VibeEnrichmentResult(
        enriched=stats.enriched,
        cached=stats.cached,
        failed=stats.failed,
        llm_calls=stats.llm_calls,
        vibes=_pool_vibes_state(db, current_user, set_obj),
    )


# ---------------------------------------------------------------------------
# Export (issue #396) — preflight resolution check + Tidal / file exports.
# The unresolved-track interrupt is enforced server-side: exports return 409
# unless the DJ explicitly opted to skip (never silently dropped).


def _unresolved_out(
    tracks: list[export_common.ExportTrack],
    reason: Literal["no_tidal_match", "missing_metadata"],
) -> list[UnresolvedTrackOut]:
    return [
        UnresolvedTrackOut(
            position=t.position,
            title=t.title,
            artist=t.artist,
            track_id=t.track_id,
            reason=reason,
        )
        for t in tracks
    ]


def _unresolved_409(unresolved: list[UnresolvedTrackOut]) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "unresolved_tracks",
            "unresolved": [u.model_dump() for u in unresolved],
        },
    )


_UNRESOLVED_409_RESPONSE = {
    "model": UnresolvedTracksError,
    "description": "Unresolved tracks — retry with skip_unresolved=true to proceed.",
}


@router.post("/sets/{set_id}/export/preflight", response_model=ExportPreflightOut)
@limiter.limit("5/minute")
def export_preflight(
    set_id: int,
    payload: ExportPreflightIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ExportPreflightOut:
    """Pre-export resolution check (tidal targets do live Tidal matching)."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    source, tracks = export_common.collect_export_tracks(set_obj)

    if payload.target == "tidal":
        if not current_user.tidal_access_token:
            return ExportPreflightOut(
                target=payload.target,
                source=source,
                total=len(tracks),
                resolved_count=0,
                unresolved=[],
                tidal_connected=False,
            )
        resolved, unresolved = export_tidal.resolve_for_tidal(db, current_user, tracks)
        return ExportPreflightOut(
            target=payload.target,
            source=source,
            total=len(tracks),
            resolved_count=len(resolved),
            unresolved=_unresolved_out(unresolved, "no_tidal_match"),
            tidal_connected=True,
        )

    unresolved = export_files.file_unresolved(tracks)
    return ExportPreflightOut(
        target=payload.target,
        source=source,
        total=len(tracks),
        resolved_count=len(tracks) - len(unresolved),
        unresolved=_unresolved_out(unresolved, "missing_metadata"),
    )


@router.post(
    "/sets/{set_id}/export/tidal",
    response_model=ExportTidalOut,
    responses={
        400: {"description": "Tidal account not connected, or no exportable tracks."},
        409: _UNRESOLVED_409_RESPONSE,
        502: {"description": "Upstream Tidal export failed."},
    },
)
@limiter.limit("5/minute")
def export_set_tidal(
    set_id: int,
    payload: ExportTidalIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ExportTidalOut:
    """Export the setlist to a fresh Tidal playlist (DJ's existing OAuth)."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    if not current_user.tidal_access_token:
        raise HTTPException(status_code=400, detail="Tidal account not connected")
    _, tracks = export_common.collect_export_tracks(set_obj)
    if not tracks:
        raise HTTPException(status_code=400, detail="Set has no tracks to export")

    resolved, unresolved = export_tidal.resolve_for_tidal(db, current_user, tracks)
    if unresolved and not payload.skip_unresolved:
        raise _unresolved_409(_unresolved_out(unresolved, "no_tidal_match"))
    if not resolved:
        raise HTTPException(status_code=400, detail="No resolvable tracks to export")

    try:
        outcome = export_tidal.export_to_tidal(db, current_user, set_obj, resolved)
    except export_tidal.TidalNotConnected:
        raise HTTPException(status_code=400, detail="Tidal account not connected") from None
    except export_tidal.TidalExportError:
        raise HTTPException(status_code=502, detail="Tidal export failed") from None

    return ExportTidalOut(
        playlist_id=outcome.playlist_id,
        playlist_url=outcome.playlist_url,
        added=outcome.added,
        skipped=len(unresolved),
        exported_at=set_obj.exported_at,
        status=set_obj.status,
    )


# Engine DJ and Lexicon both import Rekordbox DJ_PLAYLISTS XML — no separate
# native format exists — so they reuse the same renderer under distinct keys.
_FILE_RENDERERS = {
    "rekordbox": (export_files.render_rekordbox_xml, "application/xml", "xml"),
    "enginedj": (export_files.render_rekordbox_xml, "application/xml", "xml"),
    "lexicon": (export_files.render_rekordbox_xml, "application/xml", "xml"),
    "m3u": (export_files.render_m3u, "audio/x-mpegurl", "m3u8"),
    "txt": (export_files.render_txt, "text/plain", "txt"),
}


_FILE_DOWNLOAD_SCHEMA = {"schema": {"type": "string", "format": "binary"}}


@router.post(
    "/sets/{set_id}/export/file",
    response_class=Response,
    responses={
        200: {
            "description": "Setlist file download (Content-Disposition: attachment).",
            "content": {
                "application/xml": _FILE_DOWNLOAD_SCHEMA,
                "audio/x-mpegurl": _FILE_DOWNLOAD_SCHEMA,
                "text/plain": _FILE_DOWNLOAD_SCHEMA,
            },
        },
        400: {"description": "Set has no tracks to export."},
        409: _UNRESOLVED_409_RESPONSE,
    },
)
@limiter.limit("10/minute")
def export_set_file(
    set_id: int,
    payload: ExportFileIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    """Download the setlist as Rekordbox XML, M3U8, or plaintext."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    _, tracks = export_common.collect_export_tracks(set_obj)
    if not tracks:
        raise HTTPException(status_code=400, detail="Set has no tracks to export")

    unresolved = export_files.file_unresolved(tracks)
    if unresolved and not payload.skip_unresolved:
        raise _unresolved_409(_unresolved_out(unresolved, "missing_metadata"))
    exportable = [t for t in tracks if t.has_metadata]

    render, media_type, ext = _FILE_RENDERERS[payload.format]
    content = render(set_obj.name, exportable)
    filename = export_files.safe_filename(set_obj.name, ext)
    return Response(
        content=content,
        media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
