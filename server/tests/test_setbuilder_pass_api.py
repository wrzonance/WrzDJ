"""API tests for WrzDJSet pass 1/pass 2 endpoints (#390)."""

from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.services.llm.base import ChatResponse, ToolCall


def _mk_set(client, auth_headers, *, name="Pass Set"):
    resp = client.post("/api/setbuilder/sets", json={"name": name}, headers=auth_headers)
    assert resp.status_code == 201, resp.json()
    return resp.json()


def _mk_pool(db, set_id: int) -> None:
    source = SetPoolSource(set_id=set_id, kind="manual", label="Manual")
    db.add(source)
    db.flush()
    for idx in range(4):
        db.add(
            SetPoolTrack(
                set_id=set_id,
                source_id=source.id,
                track_id=f"tidal:{idx}",
                title=f"Track {idx}",
                artist=f"Artist {idx}",
                bpm=124 + idx,
                key="8A",
                camelot="8A",
                energy=5 + idx,
                duration_sec=210,
                dedupe_sig=f"sig-{idx}",
            )
        )
    db.commit()


def test_build_set_requires_confirmation(client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)
    _mk_pool(db, set_obj["id"])

    resp = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/build",
        json={"confirmed": False},
        headers=auth_headers,
    )

    assert resp.status_code == 400
    assert "confirmation" in resp.json()["detail"].lower()


def test_build_set_endpoint_creates_timeline(client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)
    _mk_pool(db, set_obj["id"])

    resp = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/build",
        json={"confirmed": True},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["slot_count"] == 4
    assert len(body["slots"]) == 4
    assert body["transition_scores"]
    assert body["slots"][0]["title"] == "Track 0"


def test_pass_endpoints_owner_isolation(client, auth_headers, db, test_user):
    from app.models.set import Set
    from app.models.user import User
    from app.services.auth import get_password_hash

    other = User(username="otherpass", password_hash=get_password_hash("password1234"), role="dj")
    db.add(other)
    db.flush()
    theirs = Set(owner_id=other.id, name="Theirs")
    db.add(theirs)
    db.commit()

    resp = client.post(
        f"/api/setbuilder/sets/{theirs.id}/build",
        json={"confirmed": True},
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_critique_endpoint_uses_gateway(monkeypatch, client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)
    _mk_pool(db, set_obj["id"])
    client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/build",
        json={"confirmed": True},
        headers=auth_headers,
    )

    async def fake_dispatch(*args, **kwargs):
        return ChatResponse(
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(
                    id="critique-1",
                    name="critique_set",
                    input={
                        "overall_grade": "A-",
                        "summary": "Clean energy arc.",
                        "flags": [{"type": "transition_brilliant", "slot_position": 1}],
                    },
                )
            ],
        )

    monkeypatch.setattr("app.services.setbuilder.pass2_agent.Gateway.dispatch", fake_dispatch)

    resp = client.post(f"/api/setbuilder/sets/{set_obj['id']}/critique", headers=auth_headers)

    assert resp.status_code == 200, resp.json()
    assert resp.json()["overall_grade"] == "A-"
    assert resp.json()["flags"][0]["type"] == "transition_brilliant"


def test_agent_chat_applies_tool_and_returns_scores(monkeypatch, client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)
    _mk_pool(db, set_obj["id"])
    built = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/build",
        json={"confirmed": True},
        headers=auth_headers,
    ).json()
    first, second = built["slots"][0], built["slots"][1]

    async def fake_dispatch(*args, **kwargs):
        return ChatResponse(
            text="Swapped.",
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(
                    id="swap-1",
                    name="swap_slots",
                    input={
                        "slot_a_id": first["id"],
                        "slot_b_id": second["id"],
                        "rationale": "Open with the better transition.",
                    },
                )
            ],
        )

    monkeypatch.setattr("app.services.setbuilder.pass2_agent.Gateway.dispatch", fake_dispatch)

    resp = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/agent/chat",
        json={"message": "Swap the opener"},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["tool_calls"][0]["args"]["slot_a_id"] == first["id"]
    assert body["tool_calls"][0]["rationale"] == "Open with the better transition."
    assert body["slots"][0]["track_id"] == second["track_id"]
    assert body["affected_transition_scores"]
