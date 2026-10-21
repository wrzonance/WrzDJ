"""Pool-store fallbacks retain safe exception context in operational logs."""

import logging

from app.services.setbuilder import pool
from app.services.setbuilder.pool_types import PoolCandidate


def test_hydration_fallback_logs_exception_class_without_error_message(db, caplog, monkeypatch):
    # Baseline 57cfcdc6867f logged provider/persistence failures without their safe class context.
    candidate = PoolCandidate(title="Night Drive", artist="DJ Example")
    secret_marker = "provider-token=must-not-be-logged"

    def fail_store_lookup(*_args, **_kwargs):
        raise RuntimeError(secret_marker)

    monkeypatch.setattr(pool, "get_track", fail_store_lookup)

    with caplog.at_level(logging.WARNING, logger="app.services.setbuilder.pool"):
        result = pool.hydrate_candidates_from_store(db, [candidate])

    assert result == [candidate]
    assert "RuntimeError" in caplog.text
    assert secret_marker not in caplog.text


def test_upsert_fallback_logs_exception_class_without_error_message(db, caplog, monkeypatch):
    # Baseline 57cfcdc6867f logged provider/persistence failures without their safe class context.
    candidate = PoolCandidate(title="Night Drive", artist="DJ Example", bpm=126)
    secret_marker = "provider-token=must-not-be-logged"

    monkeypatch.setattr(pool, "get_track", lambda *_args, **_kwargs: None)

    def fail_upsert(*_args, **_kwargs):
        raise ValueError(secret_marker)

    monkeypatch.setattr(pool, "upsert_track", fail_upsert)

    with caplog.at_level(logging.WARNING, logger="app.services.setbuilder.pool"):
        result = pool.hydrate_candidates_from_store(db, [candidate])

    assert result == [candidate]
    assert "ValueError" in caplog.text
    assert secret_marker not in caplog.text
    assert db.is_active
