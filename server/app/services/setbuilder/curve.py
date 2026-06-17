"""Energy-curve templates + interpolation for WrzDJSet (#389, exec summary §3).

The curve is *derived*: it connects each slot's ``target_energy`` at the
slot's midpoint. Templates (built-in or per-DJ persisted) are normalized
point lists ``{t: 0-1, e: 0-10, label}``; applying a template interpolates
the template shape at every slot midpoint (piecewise linear, exec summary
§11 default) and persists the result onto ``SetSlot.target_energy``.

Vibe windows persist as *paired* ``SetCurvePoint`` rows: the start row sets
``is_slow_window_start`` + carries the label; the end row sets
``is_slow_window_end``. Window rows use ``energy=0`` — they do not
contribute to the energy envelope (the envelope comes from slot targets).
"""

import json

from sqlalchemy.orm import Session

from app.models.curve_template import SetCurveTemplate
from app.models.set import Set, SetCurvePoint, SetSlot

# Built-in templates (design-bundle CURVE_PRESETS). ``slow_start``/``slow_end``
# flags mark suggested vibe-window boundaries the client rebuilds on apply.
BUILTIN_TEMPLATES: dict[str, list[dict]] = {
    "Open-Format": [
        {"t": 0, "e": 4, "label": "Arrival"},
        {"t": 0.10, "e": 5, "label": "Warm-up"},
        {"t": 0.25, "e": 7, "label": "Lift"},
        {"t": 0.45, "e": 9, "label": "Peak I"},
        {"t": 0.55, "e": 7, "label": "Breather", "slow_start": True},
        {"t": 0.62, "e": 5, "label": "Slow set", "slow_end": True},
        {"t": 0.72, "e": 8, "label": "Re-energize"},
        {"t": 0.85, "e": 10, "label": "Peak II"},
        {"t": 0.95, "e": 6, "label": "Last call"},
        {"t": 1.0, "e": 3, "label": "Close"},
    ],
    "Wedding": [
        {"t": 0, "e": 3, "label": "Cocktail"},
        {"t": 0.15, "e": 4, "label": "Dinner"},
        {"t": 0.3, "e": 6, "label": "First sets"},
        {"t": 0.5, "e": 9, "label": "Peak"},
        {"t": 0.7, "e": 5, "label": "Slow songs", "slow_start": True},
        {"t": 0.78, "e": 4, "label": "Slow end", "slow_end": True},
        {"t": 0.88, "e": 9, "label": "Closer peak"},
        {"t": 1.0, "e": 6, "label": "Send-off"},
    ],
    "Prom": [
        {"t": 0, "e": 5, "label": "Arrival"},
        {"t": 0.2, "e": 8, "label": "Lift"},
        {"t": 0.4, "e": 10, "label": "Peak I"},
        {"t": 0.55, "e": 6, "label": "Slow", "slow_start": True},
        {"t": 0.65, "e": 5, "label": "Slow", "slow_end": True},
        {"t": 0.85, "e": 10, "label": "Peak II"},
        {"t": 1.0, "e": 7, "label": "Close"},
    ],
    "Club Peak": [
        {"t": 0, "e": 7, "label": "Warm"},
        {"t": 0.3, "e": 9, "label": "Build"},
        {"t": 0.6, "e": 10, "label": "Peak"},
        {"t": 0.85, "e": 10, "label": "Hold"},
        {"t": 1.0, "e": 8, "label": "Cool"},
    ],
}


# ---------------------------------------------------------------------------
# Interpolation (piecewise linear)
# ---------------------------------------------------------------------------


def interpolate_energy(points: list[dict], t: float) -> float:
    """Energy of the curve at normalized position ``t`` (clamped to [0, 1]).

    Piecewise-linear between consecutive points; flat extension before the
    first / after the last point.
    """
    if not points:
        return 5.0
    t = max(0.0, min(1.0, t))
    if t <= points[0]["t"]:
        return float(points[0]["e"])
    if t >= points[-1]["t"]:
        return float(points[-1]["e"])
    for a, b in zip(points, points[1:]):
        if a["t"] <= t <= b["t"]:
            span = b["t"] - a["t"]
            if span <= 0:
                return float(b["e"])
            f = (t - a["t"]) / span
            return float(a["e"]) + (float(b["e"]) - float(a["e"])) * f
    return float(points[-1]["e"])


def targets_at_midpoints(points: list[dict], midpoints: list[float]) -> list[float]:
    """Interpolated targets (rounded to 0.1) at each slot midpoint."""
    return [round(interpolate_energy(points, m), 1) for m in midpoints]


def uniform_midpoints(n: int) -> list[float]:
    """Uniform slot midpoints for ``n`` slots: (i + 0.5) / n."""
    return [(i + 0.5) / n for i in range(n)]


def windows_from_points(points: list[dict]) -> list[dict]:
    """Pair slow_start/slow_end flags into ``{t0, t1}`` windows."""
    windows: list[dict] = []
    open_t: float | None = None
    for p in points:
        if p.get("slow_start"):
            open_t = p["t"]
        if p.get("slow_end") and open_t is not None:
            windows.append({"t0": open_t, "t1": p["t"]})
            open_t = None
    return windows


# ---------------------------------------------------------------------------
# Template CRUD (owner-scoped)
# ---------------------------------------------------------------------------


def template_points(tpl: SetCurveTemplate) -> list[dict]:
    """Decode a template's stored point list."""
    return json.loads(tpl.points_json)


def list_templates(db: Session, user_id: int) -> list[SetCurveTemplate]:
    """The DJ's saved templates, newest first."""
    return (
        db.query(SetCurveTemplate)
        .filter(SetCurveTemplate.user_id == user_id)
        .order_by(SetCurveTemplate.updated_at.desc())
        .all()
    )


def get_owned_template(db: Session, template_id: int, user_id: int) -> SetCurveTemplate | None:
    """Fetch a template by id, scoped to the owner. None if missing/unowned."""
    return (
        db.query(SetCurveTemplate)
        .filter(SetCurveTemplate.id == template_id, SetCurveTemplate.user_id == user_id)
        .one_or_none()
    )


def create_template(db: Session, user_id: int, name: str, points: list[dict]) -> SetCurveTemplate:
    """Persist a new per-DJ template."""
    tpl = SetCurveTemplate(user_id=user_id, name=name, points_json=json.dumps(points))
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


def update_template(
    db: Session, tpl: SetCurveTemplate, name: str, points: list[dict]
) -> SetCurveTemplate:
    """Overwrite a template's name + points."""
    tpl.name = name
    tpl.points_json = json.dumps(points)
    db.commit()
    db.refresh(tpl)
    return tpl


def delete_template(db: Session, tpl: SetCurveTemplate) -> None:
    """Delete a template."""
    db.delete(tpl)
    db.commit()


# ---------------------------------------------------------------------------
# Slot targets
# ---------------------------------------------------------------------------


def apply_points_to_slots(
    db: Session,
    set_obj: Set,
    points: list[dict],
    midpoints: list[float] | None,
) -> list[tuple[int, float]]:
    """Re-target every slot from the template shape; persist + return targets.

    ``midpoints`` are normalized slot midpoints supplied by the client (which
    knows track durations). When None, slots are treated as uniform buckets.

    Raises ValueError when the midpoint count doesn't match the slot count.
    """
    slots = (
        db.query(SetSlot)
        .filter(SetSlot.set_id == set_obj.id)
        .order_by(SetSlot.position.asc())
        .all()
    )
    if not slots:
        return []
    if midpoints is None:
        midpoints = uniform_midpoints(len(slots))
    elif len(midpoints) != len(slots):
        raise ValueError(f"expected {len(slots)} slot_midpoints, got {len(midpoints)}")

    targets = targets_at_midpoints(points, midpoints)
    for slot, target in zip(slots, targets):
        slot.target_energy = target
    db.commit()
    return [(slot.id, target) for slot, target in zip(slots, targets)]


def set_slot_target(db: Session, slot: SetSlot, value: float | None) -> SetSlot:
    """Set (or clear, with None) a slot's explicit energy target."""
    slot.target_energy = value if value is None else round(value, 1)
    db.commit()
    db.refresh(slot)
    return slot


# ---------------------------------------------------------------------------
# Vibe windows (paired SetCurvePoint rows)
# ---------------------------------------------------------------------------


def get_vibe_windows(db: Session, set_id: int) -> list[dict]:
    """Decode paired window rows into ``{t0_sec, t1_sec, label}`` dicts.

    Rows are read in insertion (id) order — ``replace_vibe_windows`` writes
    each window as an adjacent start/end pair, which keeps pairing correct
    even when windows overlap in time.
    """
    rows = (
        db.query(SetCurvePoint)
        .filter(
            SetCurvePoint.set_id == set_id,
            (SetCurvePoint.is_slow_window_start == True)  # noqa: E712
            | (SetCurvePoint.is_slow_window_end == True),  # noqa: E712
        )
        .order_by(SetCurvePoint.id.asc())
        .all()
    )
    windows: list[dict] = []
    open_row: SetCurvePoint | None = None
    for row in rows:
        if row.is_slow_window_start:
            open_row = row
        elif row.is_slow_window_end and open_row is not None:
            windows.append(
                {
                    "t0_sec": open_row.position_sec,
                    "t1_sec": row.position_sec,
                    "label": open_row.label or "Vibe window",
                }
            )
            open_row = None
    return windows


def replace_vibe_windows(
    db: Session, set_obj: Set, windows: list[dict], *, commit: bool = True
) -> list[dict]:
    """Replace-all vibe windows for a set; returns the stored windows."""
    db.query(SetCurvePoint).filter(
        SetCurvePoint.set_id == set_obj.id,
        (SetCurvePoint.is_slow_window_start == True)  # noqa: E712
        | (SetCurvePoint.is_slow_window_end == True),  # noqa: E712
    ).delete(synchronize_session=False)

    for w in sorted(windows, key=lambda w: w["t0_sec"]):
        db.add(
            SetCurvePoint(
                set_id=set_obj.id,
                position_sec=w["t0_sec"],
                energy=0,
                label=w["label"],
                is_slow_window_start=True,
            )
        )
        db.add(
            SetCurvePoint(
                set_id=set_obj.id,
                position_sec=w["t1_sec"],
                energy=0,
                is_slow_window_end=True,
            )
        )
    if commit:
        db.commit()
    else:
        db.flush()
    return get_vibe_windows(db, set_obj.id)
