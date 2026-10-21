"""Runtime-validated payload contracts for the SetBuilder agent tool boundary."""

from __future__ import annotations

from collections.abc import Callable
from typing import (
    Annotated,
    Any,
    Generic,
    Literal,
    NotRequired,
    Required,
    TypedDict,
    TypeVar,
    get_args,
)

from pydantic import ConfigDict, Field, TypeAdapter, ValidationError, with_config
from sqlalchemy.orm import Session

from app.models.set import Set
from app.schemas.setbuilder_agent import AgentCritiqueFlagType as CritiqueFlagType
from app.services.setbuilder.agent.agent_common import AgentToolError


@with_config(ConfigDict(extra="allow", strict=True))
class ToolPayload(TypedDict, total=False):
    """Strict JSON fields with extra keys retained, matching existing tool schemas."""


CRITIQUE_FLAG_TYPES = get_args(CritiqueFlagType)
BuiltinCurveTemplate = Literal["Open-Format", "Wedding", "Prom", "Club Peak"]


class ReorderSlotPayload(ToolPayload):
    slot_id: Required[int]
    position: Required[int]
    rationale: Required[str]


class MoveRangePayload(ToolPayload):
    start_position: Required[int]
    end_position: Required[int]
    to_position: Required[int]
    rationale: Required[str]


class SwapSlotsPayload(ToolPayload):
    slot_a_id: Required[int]
    slot_b_id: Required[int]
    rationale: Required[str]


class RemoveSlotPayload(ToolPayload):
    slot_id: Required[int]
    rationale: Required[str]


class ReplaceSlotPayload(ToolPayload):
    slot_id: Required[int]
    pool_track_id: Required[int]
    rationale: Required[str]


class InsertFromPoolPayload(ToolPayload):
    pool_track_id: Required[int]
    position: Required[int]
    rationale: Required[str]


class SearchAndInsertPayload(ToolPayload):
    query: Required[str]
    position: Required[int]
    rationale: Required[str]


class AddSlowWindowPayload(ToolPayload):
    t0_sec: Required[int]
    t1_sec: Required[int]
    label: Required[str]
    rationale: Required[str]


class SetPeakAtPayload(ToolPayload):
    position: Required[int]
    energy: Required[float]
    rationale: Required[str]


class BumpEnergyPayload(ToolPayload):
    amount: Required[float]
    slot_id: NotRequired[int]
    rationale: Required[str]


class SetCurvePointPayload(ToolPayload):
    position_sec: Required[int]
    energy: Required[int]
    label: NotRequired[str]
    rationale: Required[str]


class RemoveCurvePointPayload(ToolPayload):
    position_sec: Required[int]
    rationale: Required[str]


class ApplyCurveTemplatePayload(ToolPayload):
    builtin: NotRequired[BuiltinCurveTemplate]
    template_id: NotRequired[int]
    rationale: Required[str]


class MutationRationalePayload(ToolPayload):
    rationale: Required[str]


class SetTargetPayload(ToolPayload):
    target_duration_sec: NotRequired[Annotated[int, Field(ge=0)] | None]
    bpm_floor: NotRequired[int | None]
    bpm_ceiling: NotRequired[int | None]
    key_strictness: NotRequired[Annotated[float, Field(ge=0.0, le=1.0)]]
    avg_transition_overlap_sec: NotRequired[Annotated[int, Field(ge=0)]]
    rationale: Required[str]


class SlotRationalePayload(ToolPayload):
    slot_id: Required[int]
    rationale: Required[str]


class AddPairingPayload(ToolPayload):
    from_pool_track_id: Required[int]
    into_pool_track_id: Required[int]
    note: NotRequired[str]
    tags: NotRequired[list[Any]]
    rationale: Required[str]


class RemovePairingPayload(ToolPayload):
    from_pool_track_id: Required[int]
    into_pool_track_id: Required[int]
    rationale: Required[str]


class ImportEventPayload(ToolPayload):
    event: Required[str]
    rationale: Required[str]


class ImportPlaylistPayload(ToolPayload):
    playlist: Required[str]
    rationale: Required[str]


class ImportUrlPayload(ToolPayload):
    url: Required[str]
    rationale: Required[str]


class TransitionPayload(ToolPayload):
    position: Required[int]


class TrackVibesPayload(ToolPayload):
    slot_id: Required[int]


class EmptyPayload(ToolPayload):
    pass


class CritiqueFlagPayload(ToolPayload):
    type: Required[CritiqueFlagType]
    slot_position: NotRequired[int]
    message: NotRequired[str]


class CritiqueSetPayload(ToolPayload):
    overall_grade: Required[str]
    summary: NotRequired[str]
    flags: Required[list[CritiqueFlagPayload]]


PayloadT = TypeVar("PayloadT")
ToolResult = tuple[dict[str, Any], set[int]]


class ValidatedToolHandler(Generic[PayloadT]):
    """Keep a handler paired with the input contract that validates its payload."""

    def __init__(
        self,
        name: str,
        payload_type: type[PayloadT],
        handler: Callable[[Session, Set, PayloadT], ToolResult],
        field_errors: dict[str, str] | None = None,
        pre_validate: Callable[[object], None] | None = None,
    ) -> None:
        self.name = name
        self.adapter = TypeAdapter(payload_type)
        self.handler = handler
        self.field_errors = field_errors or {}
        self.pre_validate = pre_validate

    def apply(self, db: Session, set_obj: Set, payload: object) -> ToolResult:
        if self.pre_validate is not None:
            self.pre_validate(payload)
        try:
            validated = self.adapter.validate_python(payload, strict=True)
        except ValidationError as exc:
            first_error = exc.errors()[0]
            location = ".".join(str(part) for part in first_error["loc"])
            field_error = self.field_errors.get(location)
            if field_error is not None:
                raise AgentToolError(field_error) from exc
            suffix = f" at {location}" if location else ""
            raise AgentToolError(f"Invalid input for {self.name}{suffix}.") from exc
        return self.handler(db, set_obj, validated)
