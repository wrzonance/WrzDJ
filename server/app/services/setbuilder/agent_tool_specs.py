"""Tool-spec registry for the WrzDJSet agent (#442).

``_agent_tools`` is the single source of which tools the model may call; the
closed allowlist in ``apply_tool_call`` must stay in sync with it.
"""

from __future__ import annotations

from app.services.llm.base import ToolSpec
from app.services.setbuilder import curve


def _critique_tool() -> ToolSpec:
    return ToolSpec(
        name="critique_set",
        description="Return a structured critique for the current set.",
        input_schema={
            "type": "object",
            "properties": {
                "overall_grade": {"type": "string"},
                "summary": {"type": "string"},
                "flags": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": [
                                    "energy_dip",
                                    "vibe_clash",
                                    "era_jump",
                                    "sing_along_missing",
                                    "banger_buried",
                                    "transition_brilliant",
                                ],
                            },
                            "slot_position": {"type": "integer"},
                            "message": {"type": "string"},
                        },
                        "required": ["type"],
                    },
                },
            },
            "required": ["overall_grade", "flags"],
        },
    )


def _agent_tools() -> list[ToolSpec]:
    return [
        _tool("reorder_slot", {"slot_id": "integer", "position": "integer"}),
        _tool(
            "move_range",
            {"start_position": "integer", "end_position": "integer", "to_position": "integer"},
        ),
        _tool("swap_slots", {"slot_a_id": "integer", "slot_b_id": "integer"}),
        _tool("remove_slot", {"slot_id": "integer"}),
        _tool("replace_slot", {"slot_id": "integer", "pool_track_id": "integer"}),
        _tool("insert_from_pool", {"pool_track_id": "integer", "position": "integer"}),
        _tool("search_and_insert", {"query": "string", "position": "integer"}),
        _tool("add_slow_window", {"t0_sec": "integer", "t1_sec": "integer", "label": "string"}),
        _tool("set_peak_at", {"position": "integer", "energy": "number"}),
        _tool("bump_energy", {"amount": "number", "slot_id": "integer"}),
        _tool(
            "set_curve_point",
            {"position_sec": "integer", "energy": "integer"},
            optional_fields={"label": "string"},
        ),
        _tool("remove_curve_point", {"position_sec": "integer"}),
        _tool("lock_slot", {"slot_id": "integer"}),
        _tool("unlock_slot", {"slot_id": "integer"}),
        _tool(
            "add_pairing",
            {"from_pool_track_id": "integer", "into_pool_track_id": "integer"},
            optional_fields={"note": "string", "tags": "array"},
        ),
        _tool(
            "remove_pairing",
            {"from_pool_track_id": "integer", "into_pool_track_id": "integer"},
        ),
        ToolSpec(
            name="set_target",
            description=(
                "Set the set's goals: total duration, BPM window, key strictness, and "
                "average transition overlap. All target fields are optional — set only "
                "those you want to change; omit the rest. The _tool() helper marks every "
                "field required, so this uses a bare ToolSpec to keep the targets optional "
                "while still requiring rationale (enforced via MUTATION_TOOLS)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "target_duration_sec": {"type": ["integer", "null"], "minimum": 0},
                    "bpm_floor": {"type": ["integer", "null"]},
                    "bpm_ceiling": {"type": ["integer", "null"]},
                    "key_strictness": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "avg_transition_overlap_sec": {"type": "integer", "minimum": 0},
                    "rationale": {"type": "string"},
                },
                "required": ["rationale"],
            },
        ),
        ToolSpec(
            name="apply_curve_template",
            description=(
                "Re-target every unlocked slot's energy from an energy-curve "
                "template shape. Provide exactly one of builtin (a preset name) "
                "or template_id (one of the DJ's saved templates)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "builtin": {
                        "type": "string",
                        "enum": sorted(curve.BUILTIN_TEMPLATES.keys()),
                    },
                    "template_id": {"type": "integer"},
                    "rationale": {"type": "string"},
                },
                "required": ["rationale"],
            },
        ),
        ToolSpec(
            name="analyze_transition",
            description="Analyze one transition by destination slot position.",
            input_schema={
                "type": "object",
                "properties": {"position": {"type": "integer"}},
                "required": ["position"],
            },
        ),
        ToolSpec(
            name="explain_transition",
            description="Explain why a transition is flagged, grounded in the two tracks' fields.",
            input_schema={
                "type": "object",
                "properties": {"position": {"type": "integer"}},
                "required": ["position"],
            },
        ),
        ToolSpec(
            name="get_track_vibes",
            description="Read the resolved vibe tags (energy, mood, source) for one slot's track.",
            input_schema={
                "type": "object",
                "properties": {"slot_id": {"type": "integer"}},
                "required": ["slot_id"],
            },
        ),
        ToolSpec(
            name="summarize_set",
            description=(
                "Read-only snapshot of the whole set: total vs target duration, "
                "BPM arc, Camelot key journey, and energy profile."
            ),
            input_schema={"type": "object", "properties": {}, "required": []},
        ),
        ToolSpec(
            name="analyze_pool_gaps",
            description=("Report pool coverage holes: missing Camelot keys and sparse BPM bands."),
            input_schema={"type": "object", "properties": {}},
        ),
        ToolSpec(
            name="suggest_pairings",
            description=(
                "Read-only: the set's consecutive transitions with their score and "
                "whether each is already pinned as a DJ pairing, plus each endpoint's "
                "pool_track_id so strong unpinned ones can be pinned with add_pairing."
            ),
            input_schema={"type": "object", "properties": {}},
        ),
        _critique_tool(),
    ]


def _tool(
    name: str,
    fields: dict[str, str],
    *,
    optional_fields: dict[str, str] | None = None,
) -> ToolSpec:
    """Build a mutation tool schema.

    ``fields`` are required; ``optional_fields`` appear in the schema but are
    not required. ``rationale`` is always added and required (mutation tools
    must justify themselves — see ``MUTATION_TOOLS``).
    """
    properties = {key: {"type": value} for key, value in fields.items()}
    properties.update({key: {"type": value} for key, value in (optional_fields or {}).items()})
    properties["rationale"] = {"type": "string"}
    return ToolSpec(
        name=name,
        description=f"Mutate the WrzDJSet timeline with {name}.",
        input_schema={
            "type": "object",
            "properties": properties,
            "required": [*fields.keys(), "rationale"],
        },
    )
