"""SSE stream-test endpoint: auth, ownership, content-type, body shape."""

from __future__ import annotations

import json
from threading import get_ident

from app.models.llm_connector import LlmCallLog, LlmConnector
from app.models.user import User
from app.services.auth import get_password_hash
from app.services.llm.adapters.openai_apikey import OpenAIApiKeyAdapter
from app.services.llm.base import ChatResponseChunk, TokenUsage


def _make_connector(db, user, *, display_name="Test", model_hint="gpt-5-mini") -> LlmConnector:
    row = LlmConnector(
        user_id=user.id,
        connector_type="openai_apikey",
        display_name=display_name,
        status="active",
        credentials=json.dumps({"api_key": "sk-fake"}),
        model_hint=model_hint,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _parse_sse(body: str) -> list[dict]:
    return [
        json.loads(line[len("data:") :].strip())
        for line in body.splitlines()
        if line.startswith("data:")
    ]


def test_stream_test_requires_auth(client, db, test_user):
    connector = _make_connector(db, test_user)
    resp = client.post(f"/api/llm/connectors/{connector.id}/stream-test")
    assert resp.status_code == 401


def test_stream_test_404_for_unowned(client, db, test_user, auth_headers):
    other = User(username="other", password_hash=get_password_hash("x123456789"), role="dj")
    db.add(other)
    db.commit()
    db.refresh(other)
    connector = _make_connector(db, other)
    resp = client.post(f"/api/llm/connectors/{connector.id}/stream-test", headers=auth_headers)
    assert resp.status_code == 404


def test_stream_test_streams_chunks(client, db, test_user, auth_headers, monkeypatch):
    from app.api import llm as llm_api

    connector = _make_connector(db, test_user)
    lookup_thread: int | None = None
    stream_threads: list[int] = []
    original_lookup = llm_api._get_owned_connector_or_404

    def track_lookup(db, connector_id, user_id):
        nonlocal lookup_thread
        lookup_thread = get_ident()
        return original_lookup(db, connector_id, user_id)

    monkeypatch.setattr(llm_api, "_get_owned_connector_or_404", track_lookup)

    async def _fake_stream(self, request):
        stream_threads.append(get_ident())
        yield ChatResponseChunk(text_delta="Hi")
        yield ChatResponseChunk(text_delta=" there")
        yield ChatResponseChunk(
            stop_reason="end_turn", usage=TokenUsage(prompt=2, completion=2), done=True
        )

    monkeypatch.setattr(OpenAIApiKeyAdapter, "stream", _fake_stream)

    resp = client.post(f"/api/llm/connectors/{connector.id}/stream-test", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    payloads = _parse_sse(resp.text)
    text = "".join(p.get("text_delta", "") for p in payloads)
    assert "Hi there" in text
    assert any(p.get("done") for p in payloads)
    assert lookup_thread is not None
    assert stream_threads
    assert lookup_thread != stream_threads[0]


def test_stream_test_uses_requested_connector_not_dj_default(
    client, db, test_user, auth_headers, monkeypatch
):
    # Regression for 57cfcdc6867f: a probe for connector B must not stream
    # through the DJ's default connector A.
    default_connector = _make_connector(db, test_user, display_name="Default", model_hint="model-a")
    requested_connector = _make_connector(
        db, test_user, display_name="Requested", model_hint="model-b"
    )
    default_connector.is_default = True
    db.commit()

    streams: list[tuple[int, str | None]] = []

    async def _fake_stream(self, request):
        streams.append((self.connector.id, request.model))
        yield ChatResponseChunk(text_delta="B is online")
        yield ChatResponseChunk(
            stop_reason="end_turn", usage=TokenUsage(prompt=2, completion=3), done=True
        )

    monkeypatch.setattr(OpenAIApiKeyAdapter, "stream", _fake_stream)

    resp = client.post(
        f"/api/llm/connectors/{requested_connector.id}/stream-test", headers=auth_headers
    )

    assert resp.status_code == 200
    assert "B is online" in resp.text
    assert streams == [(requested_connector.id, "model-b")]
    call = db.query(LlmCallLog).filter(LlmCallLog.purpose == "stream_test").one()
    assert call.connector_id == requested_connector.id


def test_stream_test_error_emits_sanitised_error_frame(
    client, db, test_user, auth_headers, monkeypatch
):
    from app.services.llm.exceptions import ProviderUnavailable

    connector = _make_connector(db, test_user)

    async def _boom(self, request):
        raise ProviderUnavailable("upstream secret detail")
        yield  # pragma: no cover

    monkeypatch.setattr(OpenAIApiKeyAdapter, "stream", _boom)

    resp = client.post(f"/api/llm/connectors/{connector.id}/stream-test", headers=auth_headers)
    assert resp.status_code == 200
    # An error frame is emitted as event: error with a sanitised code only.
    body = resp.text
    assert "event: error" in body
    assert "ProviderUnavailable" in body
    # The raw upstream message is never leaked.
    assert "upstream secret detail" not in body
