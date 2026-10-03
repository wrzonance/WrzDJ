"""Invite-link creation and acceptance for SetBuilder collaboration."""

import hashlib
import re
import secrets
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.set import Set, SetCollaborator
from app.models.set_collaborator_invite import SetCollaboratorInvite
from app.models.user import User

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{40,64}$")
_INVITE_LIFETIME = timedelta(days=7)


class InviteUnavailable(Exception):
    """The invite is missing, expired, revoked, or already used."""


class AlreadyCollaborator(Exception):
    """The accepting user already collaborates on this set."""


class OwnerCannotAcceptInvite(Exception):
    """A set owner cannot join their own set as a collaborator."""


class InviteAlreadyAccepted(Exception):
    """An accepted invite cannot be revoked; revoke the collaborator instead."""


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create_invite(
    db: Session, set_id: int, user: User, role: str
) -> tuple[SetCollaboratorInvite, str]:
    token = secrets.token_urlsafe(32)
    invite = SetCollaboratorInvite(
        set_id=set_id,
        token_hash=_token_hash(token),
        role=role,
        created_by=user.id,
        expires_at=utcnow() + _INVITE_LIFETIME,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite, token


def list_invites(db: Session, set_id: int) -> list[SetCollaboratorInvite]:
    return (
        db.query(SetCollaboratorInvite)
        .filter(SetCollaboratorInvite.set_id == set_id)
        .order_by(SetCollaboratorInvite.id.desc())
        .all()
    )


def revoke_invite(db: Session, invite: SetCollaboratorInvite) -> None:
    invite = (
        db.query(SetCollaboratorInvite)
        .filter(SetCollaboratorInvite.id == invite.id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    if invite.accepted_at is not None:
        raise InviteAlreadyAccepted
    if invite.revoked_at is None:
        invite.revoked_at = utcnow()
    db.commit()


def accept_invite(db: Session, token: str, user: User) -> SetCollaborator:
    if not _TOKEN_RE.fullmatch(token):
        raise InviteUnavailable
    invite = (
        db.query(SetCollaboratorInvite)
        .filter(SetCollaboratorInvite.token_hash == _token_hash(token))
        .with_for_update()
        .one_or_none()
    )
    now = utcnow()
    if (
        invite is None
        or invite.revoked_at is not None
        or invite.accepted_at is not None
        or invite.expires_at <= now
    ):
        raise InviteUnavailable
    set_owner_id = db.query(Set.owner_id).filter(Set.id == invite.set_id).scalar()
    if set_owner_id == user.id:
        raise OwnerCannotAcceptInvite
    exists = (
        db.query(SetCollaborator)
        .filter(SetCollaborator.set_id == invite.set_id, SetCollaborator.user_id == user.id)
        .first()
    )
    if exists:
        raise AlreadyCollaborator
    collaborator = SetCollaborator(
        set_id=invite.set_id,
        user_id=user.id,
        role=invite.role,
        invited_by=invite.created_by,
    )
    invite.accepted_at = now
    db.add(collaborator)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        exists = (
            db.query(SetCollaborator)
            .filter(SetCollaborator.set_id == invite.set_id, SetCollaborator.user_id == user.id)
            .first()
        )
        if exists:
            raise AlreadyCollaborator from exc
        raise
    db.refresh(collaborator)
    return collaborator


def get_invite_for_owner(db: Session, set_id: int, invite_id: int) -> SetCollaboratorInvite | None:
    return (
        db.query(SetCollaboratorInvite)
        .filter(
            SetCollaboratorInvite.id == invite_id,
            SetCollaboratorInvite.set_id == set_id,
        )
        .one_or_none()
    )
