"""Public set-builder schema boundary contracts."""

import pytest
from pydantic import ValidationError

from app.schemas.setbuilder import (
    AgentChatIn,
    ApplyTemplateRequest,
    CurveTemplateCreate,
    ExportAppleMusicRecoveryIn,
    PoolImportManualIn,
    PoolVibeOverrideIn,
    SetCreate,
    SetDocumentSettings,
)


def test_setbuilder_schema_imports_remain_available_from_compatibility_module():
    assert SetCreate(name="Evening set").event_id is None
    assert PoolImportManualIn(title="Track", artist="Artist").source_service == "manual"
    assert CurveTemplateCreate(name="Curve", points=[{"t": 0, "e": 2}, {"t": 1, "e": 8}])
    assert AgentChatIn(message="Make the set warmer").history == []


def test_setbuilder_schema_validation_and_defaults_remain_stable():
    with pytest.raises(ValidationError):
        SetCreate(name="")

    with pytest.raises(ValidationError):
        PoolImportManualIn(title="Track", artist="Artist", bpm=401)

    with pytest.raises(ValidationError):
        ApplyTemplateRequest()

    assert ApplyTemplateRequest(builtin="Warm-up").slot_midpoints is None
    assert SetDocumentSettings().key_strictness == 0.2

    with pytest.raises(ValidationError):
        SetDocumentSettings(bpm_floor=140, bpm_ceiling=120)

    assert PoolVibeOverrideIn(mood="  house  ").mood == "house"
    with pytest.raises(ValidationError):
        PoolVibeOverrideIn()

    assert (
        ExportAppleMusicRecoveryIn(action="playlist_found", playlist_id="p.house_1").action
        == "playlist_found"
    )
    with pytest.raises(ValidationError):
        ExportAppleMusicRecoveryIn(action="playlist_found")
