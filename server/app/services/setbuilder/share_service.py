"""Share-token + duplicate logic for WrzDJSet sets (issue #398).

The share token is the sole capability for the public read-only view.
It is generated with a CSPRNG (secrets.token_urlsafe), stored on the
unique-indexed ``sets.share_token`` column, and never grants access to
any mutating route (those all require an authenticated owner).
"""

import re
import secrets

from sqlalchemy.orm import Session

from app.models.set import Set, SetCurvePoint, SetSlot

_MAX_NAME = 120
_COPY_SUFFIX = " (copy)"
# token_urlsafe(32) yields 43 url-safe chars; accept a small range so a
# future size bump doesn't break old links. Anything else short-circuits.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")


def regenerate_share_token(db: Session, set_obj: Set) -> Set:
    """Create or rotate the read-only share token (CSPRNG)."""
    set_obj.share_token = secrets.token_urlsafe(32)
    db.commit()
    db.refresh(set_obj)
    return set_obj


def revoke_share_token(db: Session, set_obj: Set) -> Set:
    """Revoke sharing: NULL the token so existing links 404."""
    set_obj.share_token = None
    db.commit()
    db.refresh(set_obj)
    return set_obj


def get_set_by_share_token(db: Session, token: str) -> Set | None:
    """Indexed lookup; malformed tokens short-circuit to None (no oracle)."""
    if not _TOKEN_RE.fullmatch(token):
        return None
    return db.query(Set).filter(Set.share_token == token).one_or_none()


def duplicate_set(db: Session, src: Set) -> Set:
    """Copy a set (slots, curve, targets, vibe windows); reset lifecycle state.

    The copy is always private ("draft", no share token, no export state)
    regardless of the source's status, per issue #398.
    """
    name = src.name + _COPY_SUFFIX
    if len(name) > _MAX_NAME:
        name = src.name[: _MAX_NAME - len(_COPY_SUFFIX)] + _COPY_SUFFIX
    dup = Set(
        owner_id=src.owner_id,
        event_id=src.event_id,
        name=name,
        vibe_theme=src.vibe_theme,
        target_duration_sec=src.target_duration_sec,
        bpm_floor=src.bpm_floor,
        bpm_ceiling=src.bpm_ceiling,
        key_strictness=src.key_strictness,
        status="draft",
        sharing_mode="private",
    )
    db.add(dup)
    db.flush()
    for slot in sorted(src.slots, key=lambda s: s.position):
        db.add(
            SetSlot(
                set_id=dup.id,
                position=slot.position,
                track_id=slot.track_id,
                locked=slot.locked,
                notes=slot.notes,
                transition_score=slot.transition_score,
                transition_warnings=slot.transition_warnings,
            )
        )
    for point in src.curve_points:
        db.add(
            SetCurvePoint(
                set_id=dup.id,
                position_sec=point.position_sec,
                energy=point.energy,
                label=point.label,
                is_slow_window_start=point.is_slow_window_start,
                is_slow_window_end=point.is_slow_window_end,
            )
        )
    db.commit()
    db.refresh(dup)
    return dup
