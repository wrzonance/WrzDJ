"""Collaborator invitation routes for WrzDJSet."""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.api.setbuilder_common import get_owned_set_or_404 as _get_owned_or_404
from app.core.rate_limit import limiter
from app.models.user import User
from app.schemas.setbuilder import (
    CollaboratorAccepted,
    CollaboratorInviteCreate,
    CollaboratorInviteCreated,
    CollaboratorInviteOut,
)
from app.services.setbuilder import (
    collaboration,
)

router = APIRouter()


@router.post(
    "/sets/{set_id}/collaborator-invites",
    response_model=CollaboratorInviteCreated,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("10/minute")
def create_collaborator_invite(
    set_id: int,
    payload: CollaboratorInviteCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> CollaboratorInviteCreated:
    """Create a single-use editor or viewer invitation for an owned set."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    invite, token = collaboration.create_invite(db, set_obj.id, current_user, payload.role)
    return CollaboratorInviteCreated(token=token, role=invite.role, expires_at=invite.expires_at)


@router.get("/sets/{set_id}/collaborator-invites", response_model=list[CollaboratorInviteOut])
@limiter.limit("30/minute")
def list_collaborator_invites(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[CollaboratorInviteOut]:
    """List invitation status for an owned set without exposing invite tokens."""
    _get_owned_or_404(db, set_id, current_user)
    return [
        CollaboratorInviteOut(
            id=invite.id,
            role=invite.role,
            created_at=invite.created_at,
            expires_at=invite.expires_at,
            accepted=invite.accepted_at is not None,
            revoked=invite.revoked_at is not None,
        )
        for invite in collaboration.list_invites(db, set_id)
    ]


@router.delete("/sets/{set_id}/collaborator-invites/{invite_id}", status_code=204)
@limiter.limit("30/minute")
def revoke_collaborator_invite(
    set_id: int,
    invite_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Revoke an unused invitation for an owned set."""
    _get_owned_or_404(db, set_id, current_user)
    invite = collaboration.get_invite_for_owner(db, set_id, invite_id)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    try:
        collaboration.revoke_invite(db, invite)
    except collaboration.InviteAlreadyAccepted as exc:
        raise HTTPException(
            status_code=409, detail="Invite was accepted; revoke the collaborator instead"
        ) from exc


@router.post("/collaborator-invites/{token}/accept", response_model=CollaboratorAccepted)
@limiter.limit("10/minute")
def accept_collaborator_invite(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> CollaboratorAccepted:
    """Accept an invite with the recipient's active DJ account."""
    try:
        collaborator = collaboration.accept_invite(db, token, current_user)
    except collaboration.InviteUnavailable as exc:
        raise HTTPException(status_code=410, detail="Invite is no longer available") from exc
    except collaboration.AlreadyCollaborator as exc:
        raise HTTPException(status_code=409, detail="Already a collaborator") from exc
    except collaboration.OwnerCannotAcceptInvite as exc:
        raise HTTPException(
            status_code=409, detail="Set owners cannot accept collaborator invites"
        ) from exc
    return CollaboratorAccepted(set_id=collaborator.set_id, role=collaborator.role)
