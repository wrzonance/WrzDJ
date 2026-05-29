"""SSE stream-test endpoint: auth, ownership, content-type, body shape."""

from __future__ import annotations

import json

from app.models.llm_connector import LlmConnector
from app.models.user import User
from app.services.auth import get_password_hash
from app.services.llm.adapters.openai_apikey import OpenAIApiKeyAdapter
from app.services.llm.base import ChatResponseChunk, TokenUsage


def _make_connector(db, user) -> LlmConnector:
    row = LlmConnector(
        user_id=user.id,
        connector_type="openai_apikey",
        display_name="Test",
        status="active",
        credentials=json.dumps({"api_key": "sk-fake"}),
        model_hint="gpt-5-mini",
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
    connector = _make_connector(db, test_user)

    async def _fake_stream(self, request):
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
