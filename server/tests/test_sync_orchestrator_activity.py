import logging

from app.services.sync import orchestrator
from app.services.sync.base import SyncResult, SyncStatus


class NotFoundAdapter:
    service_name = "tidal"

    @staticmethod
    def is_sync_enabled(_event):
        return True

    @staticmethod
    def sync_track(*_args):
        return SyncResult(service="tidal", status=SyncStatus.NOT_FOUND)


def test_activity_log_failure_is_reported_without_changing_sync_result(
    db, test_request, monkeypatch, caplog
):
    monkeypatch.setattr(orchestrator, "get_connected_adapters", lambda _user: [NotFoundAdapter()])

    def fail_activity_log(*_args, **_kwargs):
        raise RuntimeError("sensitive activity payload")

    monkeypatch.setattr(
        "app.services.activity_log.log_activity_in_fresh_session", fail_activity_log
    )
    with caplog.at_level(logging.WARNING, logger="app.services.sync.orchestrator"):
        result = orchestrator.sync_request_to_services(db, test_request)

    assert result.results[0].status is SyncStatus.NOT_FOUND
    assert any(
        record.message == "Sync activity logging failed for tidal (RuntimeError)"
        for record in caplog.records
    )
    assert "sensitive activity payload" not in caplog.text
