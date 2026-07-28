"""Per-DJ reusable SetBuilder template CRUD + extract/instantiate (issue #407).

A template snapshots a source ``Set``'s target settings plus its slot
skeleton (position/locked/target_energy/notes, no track assignments) and
energy curve. ``extract_template`` copies a ``Set`` into a new template;
``instantiate_template`` is the inverse, creating a fresh draft ``Set`` from
a template with every slot's ``track_id`` unconditionally NULL.

Do not pattern-match the slot-copy loop here off ``share_service.duplicate_set``
— that precedent silently omits ``target_energy`` from its ``SetSlot`` copy
despite its own docstring claiming to copy targets. Templates require
``target_energy``.
"""

import json

from sqlalchemy.orm import Session

from app.models.set import Set, SetCurvePoint, SetSlot
from app.models.set_template import SetTemplate


def list_templates(db: Session, user_id: int) -> list[SetTemplate]:
    """The DJ's saved templates, newest first."""
    return (
        db.query(SetTemplate)
        .filter(SetTemplate.user_id == user_id)
        .order_by(SetTemplate.updated_at.desc())
        .all()
    )


def get_owned_template(db: Session, template_id: int, user_id: int) -> SetTemplate | None:
    """Fetch a template by id, scoped to the owner. None if missing/unowned."""
    return (
        db.query(SetTemplate)
        .filter(SetTemplate.id == template_id, SetTemplate.user_id == user_id)
        .one_or_none()
    )


def extract_template(db: Session, src_set: Set, user_id: int, name: str) -> SetTemplate:
    """Copy ``src_set``'s target settings + slot/curve shape into a new template.

    Strips ``track_id``/``transition_score``/``transition_warnings`` from
    every slot — templates snapshot the timeline shape, not track
    assignments. Never raises for an empty ``src_set`` (0 slots/points).
    """
    slots = _encode_slots(src_set.slots)
    curve_points = _encode_curve_points(src_set.curve_points)
    tpl = SetTemplate(
        user_id=user_id,
        name=name,
        vibe_theme=src_set.vibe_theme,
        target_duration_sec=src_set.target_duration_sec,
        avg_transition_overlap_sec=src_set.avg_transition_overlap_sec,
        bpm_floor=src_set.bpm_floor,
        bpm_ceiling=src_set.bpm_ceiling,
        key_strictness=src_set.key_strictness,
        slots_json=slots,
        curve_points_json=curve_points,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


def instantiate_template(
    db: Session, tpl: SetTemplate, owner_id: int, name: str | None, event_id: int | None
) -> Set:
    """Create a new draft/private ``Set`` from a template.

    Every created ``SetSlot`` has ``track_id=None`` and ``locked=False``
    unconditionally — see the loop below for why an empty slot must never be
    locked. ``name`` falls back to ``tpl.name`` when None/blank. ``event_id``
    is stored as given; the caller is responsible for rejecting an event the
    owner does not hold (``_require_owned_event`` in the router). Never
    raises for an empty template.
    """
    resolved_name = name.strip() if name and name.strip() else tpl.name
    new_set = Set(
        owner_id=owner_id,
        event_id=event_id,
        name=resolved_name,
        vibe_theme=tpl.vibe_theme,
        target_duration_sec=tpl.target_duration_sec,
        avg_transition_overlap_sec=tpl.avg_transition_overlap_sec,
        bpm_floor=tpl.bpm_floor,
        bpm_ceiling=tpl.bpm_ceiling,
        key_strictness=tpl.key_strictness,
        status="draft",
        sharing_mode="private",
    )
    db.add(new_set)
    db.flush()

    for slot in decode_slots(tpl.slots_json):
        db.add(
            SetSlot(
                set_id=new_set.id,
                position=slot["position"],
                track_id=None,
                # Always unlocked, even when the source slot was locked: the
                # stored `locked` flag records the source's shape, but every
                # instantiated slot is empty by design. pass1 keeps locked
                # slots verbatim and only fills unlocked ones, so a locked
                # empty slot would be a hole the builder can never fill.
                locked=False,
                notes=slot["notes"],
                target_energy=slot["target_energy"],
            )
        )
    for point in decode_curve_points(tpl.curve_points_json):
        db.add(
            SetCurvePoint(
                set_id=new_set.id,
                position_sec=point["position_sec"],
                energy=point["energy"],
                label=point["label"],
                is_slow_window_start=point["is_slow_window_start"],
                is_slow_window_end=point["is_slow_window_end"],
            )
        )
    db.commit()
    db.refresh(new_set)
    return new_set


def delete_template(db: Session, tpl: SetTemplate) -> None:
    """Delete a template."""
    db.delete(tpl)
    db.commit()


# ---------------------------------------------------------------------------
# Codec helpers (no schema import). ``decode_*`` are public — the API layer
# reads stored JSON through them, mirroring ``curve.template_points``;
# ``_encode_*`` stay private, since only this module ever writes.
# ---------------------------------------------------------------------------


def _encode_slots(slots: list[SetSlot]) -> str:
    """Slot skeleton -> JSON, sorted by position, tracks/scores stripped."""
    ordered = sorted(slots, key=lambda s: s.position)
    return json.dumps(
        [
            {
                "position": slot.position,
                "target_energy": slot.target_energy,
                "locked": slot.locked,
                "notes": slot.notes,
            }
            for slot in ordered
        ]
    )


def decode_slots(slots_json: str) -> list[dict]:
    """JSON -> slot skeleton dicts."""
    return json.loads(slots_json)


def _encode_curve_points(points: list[SetCurvePoint]) -> str:
    """Curve points -> JSON, sorted by position_sec."""
    ordered = sorted(points, key=lambda p: p.position_sec)
    return json.dumps(
        [
            {
                "position_sec": point.position_sec,
                "energy": point.energy,
                "label": point.label,
                "is_slow_window_start": point.is_slow_window_start,
                "is_slow_window_end": point.is_slow_window_end,
            }
            for point in ordered
        ]
    )


def decode_curve_points(curve_points_json: str) -> list[dict]:
    """JSON -> curve point dicts."""
    return json.loads(curve_points_json)
