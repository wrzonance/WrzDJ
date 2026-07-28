"""Pydantic schemas for per-DJ SetBuilder templates (issue #407).

``SetTemplateCurvePointModel`` mirrors ``SetDocumentCurvePoint``'s field
constraints in ``schemas/setbuilder.py`` — a template's ``curve_points_json``
decodes into that same shape. Stored slots have no schema counterpart on
purpose: they are never exposed individually, only counted
(``SetTemplateOut.slot_count``), matching how ``curve.template_points``
returns raw decoded dicts for the ``SetCurveTemplate`` precedent (#389).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

    @field_validator("name")
    @classmethod
    def _strip_and_require_non_blank(cls, value: str) -> str:
        """``min_length`` alone lets ``"   "`` through and stores a blank
        gallery entry. The dashboard already trims; direct API clients must
        not be able to bypass it."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


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
