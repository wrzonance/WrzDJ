"""Pydantic schemas for per-DJ SetBuilder templates (issue #407).

Mirrors the ``SetDocumentSlot`` / ``SetDocumentCurvePoint`` field constraints
in ``schemas/setbuilder.py`` since a template's ``slots_json`` /
``curve_points_json`` decode into the same shapes minus track assignment.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SetTemplateSlotModel(BaseModel):
    """One slot skeleton entry stored in a template's ``slots_json``.

    No ``track_id``/``transition_score``/``transition_warnings`` — templates
    snapshot the timeline shape, never track assignments.
    """

    position: int = Field(..., ge=0)
    target_energy: float | None = Field(None, ge=0.0, le=10.0)
    locked: bool = False
    notes: str | None = None


class SetTemplateCurvePointModel(BaseModel):
    """One energy-curve point stored in a template's ``curve_points_json``."""

    position_sec: int = Field(..., ge=0)
    energy: int = Field(..., ge=0, le=10)
    label: str | None = Field(None, max_length=50)
    is_slow_window_start: bool = False
    is_slow_window_end: bool = False


class SaveAsTemplateRequest(BaseModel):
    """Body for extracting a template from an existing set."""

    name: str = Field(..., min_length=1, max_length=120)


class InstantiateTemplateRequest(BaseModel):
    """Body for creating a new draft set from a template.

    ``name`` falls back to the template's own name when omitted/blank;
    ``event_id`` is passed through uncritically, matching ``SetCreate``.
    """

    name: str | None = Field(None, max_length=120)
    event_id: int | None = None


class SetTemplateOut(BaseModel):
    """A saved template for the gallery / detail surface.

    ``slot_count`` and ``curve_points`` are derived from the stored JSON at
    the API boundary — this schema is built explicitly, not read directly
    off the ``SetTemplate`` row via ``from_attributes``.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    vibe_theme: str | None
    target_duration_sec: int | None
    avg_transition_overlap_sec: int
    bpm_floor: int | None
    bpm_ceiling: int | None
    key_strictness: float
    slot_count: int
    curve_points: list[SetTemplateCurvePointModel]
    created_at: datetime
    updated_at: datetime


class SetTemplateGalleryResponse(BaseModel):
    """List payload for the template gallery (always 200, even when empty)."""

    templates: list[SetTemplateOut]
