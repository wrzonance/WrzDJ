from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.schemas.setbuilder_agent import CritiqueFlagOut
from app.services.setbuilder.agent import pass2_agent
from app.services.setbuilder.agent.agent_common import AgentToolError
from app.services.setbuilder.agent.agent_tool_specs import _agent_tools, _critique_tool


def _schema_types(schema: dict[str, object]) -> set[str]:
    declared = schema.get("type")
    if isinstance(declared, str):
        return {declared}
    if isinstance(declared, list):
        return set(declared)
    branches = schema.get("anyOf")
    if isinstance(branches, list):
        return set().union(*(_schema_types(branch) for branch in branches))
    return set()


def _schema_constraint(schema: dict[str, object], name: str) -> object:
    if name in schema:
        return schema[name]
    branches = schema.get("anyOf")
    if isinstance(branches, list):
        for branch in branches:
            if "null" not in _schema_types(branch):
                return _schema_constraint(branch, name)
    return None


def test_payload_contracts_match_public_tool_schemas() -> None:
    specs = {tool.name: tool.input_schema for tool in _agent_tools()}
    assert set(specs) == set(pass2_agent._TOOL_HANDLERS)

    for name, spec in specs.items():
        payload_schema = pass2_agent._TOOL_HANDLERS[name].adapter.json_schema()
        assert set(spec["properties"]) == set(payload_schema["properties"]), name
        assert set(spec.get("required", [])) == set(payload_schema.get("required", [])), name
        for field, spec_property in spec["properties"].items():
            payload_property = payload_schema["properties"][field]
            assert _schema_types(spec_property) == _schema_types(payload_property), (name, field)
            for constraint in ("minimum", "maximum"):
                if constraint in spec_property or _schema_constraint(payload_property, constraint):
                    assert spec_property.get(constraint) == _schema_constraint(
                        payload_property, constraint
                    ), (name, field, constraint)
            if "enum" in spec_property:
                assert set(spec_property["enum"]) == set(payload_property["enum"]), (name, field)


def test_tool_dispatch_rejects_malformed_payload_before_handler() -> None:
    # Regression for 57cfcdc6867f: direct handler key reads leaked KeyError/ValueError.
    with pytest.raises(AgentToolError, match="Invalid input for reorder_slot"):
        pass2_agent.apply_tool_call(
            None,  # type: ignore[arg-type]
            SimpleNamespace(id=1),  # type: ignore[arg-type]
            "reorder_slot",
            {"slot_id": "not-an-integer", "position": 0, "rationale": "Move it."},
        )


def test_critique_flag_contract_matches_agent_input_and_api_output() -> None:
    tool_flag_types = _critique_tool().input_schema["properties"]["flags"]["items"]["properties"][
        "type"
    ]["enum"]
    response_flag_types = CritiqueFlagOut.model_json_schema()["properties"]["type"]["enum"]

    assert tool_flag_types == response_flag_types


def test_tool_dispatch_validates_then_preserves_valid_payload(monkeypatch) -> None:
    payload = {
        "slot_id": 12,
        "position": 2,
        "rationale": "Move the track after the intro.",
        "provider_annotation": {"source": "llm"},
    }
    received: list[dict[str, object]] = []

    def handler(_db, _set_obj, validated_payload):
        received.append(validated_payload)
        return {"slot_id": validated_payload["slot_id"]}, {2}

    monkeypatch.setattr(pass2_agent._TOOL_HANDLERS["reorder_slot"], "handler", handler)

    result, positions = pass2_agent.apply_tool_call(
        None,  # type: ignore[arg-type]
        SimpleNamespace(id=1),  # type: ignore[arg-type]
        "reorder_slot",
        payload,
    )

    assert result == {"slot_id": 12}
    assert positions == {2}
    assert received == [payload]
