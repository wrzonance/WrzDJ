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


def test_build_set_response_carries_pool_coverage(client, auth_headers, db):
    # #542: the build response exposes pool coverage so the FE build-confirm
    # dialog can show "fully enriched: N/M" and a soft, overridable warning.
    set_obj = _mk_set(client, auth_headers)
    _mk_pool(db, set_obj["id"])  # 4 tracks, all fields EXCEPT genre

    resp = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/build",
        json={"confirmed": True},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.json()
    coverage = resp.json()["coverage"]
    assert coverage["pool_size"] == 4
    # Every track is missing genre → none fully covered → soft not-ready warning.
    assert coverage["fully_covered_count"] == 0
    assert coverage["missing"]["genre"] == 4
    assert coverage["missing"]["bpm"] == 0
    assert coverage["ready"] is False


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


def test_agent_history_initially_empty_without_llm(monkeypatch, client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)

    async def fail_dispatch(*args, **kwargs):
        raise AssertionError("history load must not call the LLM gateway")

    monkeypatch.setattr("app.services.setbuilder.pass2_agent.Gateway.dispatch", fail_dispatch)

    resp = client.get(
        f"/api/setbuilder/sets/{set_obj['id']}/agent/history",
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["messages"] == []
    assert body["context_summary"] is None
    assert body["uses_compact_context"] is True


def test_agent_history_handles_legacy_tool_call_without_display_summary(
    client, auth_headers, db, test_user
):
    from app.services.setbuilder import agent_history

    set_obj = _mk_set(client, auth_headers)
    session = agent_history.get_or_create_session(db, set_obj["id"], test_user.id)
    agent_history.append_message(
        db,
        session,
        role="assistant",
        content="Legacy assistant turn.",
        tool_calls=[
            {
                "id": "legacy-1",
                "name": "swap_slots",
                "args": {},
                "rationale": None,
                "result": {},
                "mutating": True,
            }
        ],
    )

    resp = client.get(
        f"/api/setbuilder/sets/{set_obj['id']}/agent/history",
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["messages"][0]["tool_calls"][0]["display_summary"] == ""


def test_agent_chat_persists_turns_and_history(monkeypatch, client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)
    _mk_pool(db, set_obj["id"])
    built = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/build",
        json={"confirmed": True},
        headers=auth_headers,
    ).json()
    first, second = built["slots"][0], built["slots"][1]

    async def fake_dispatch(db_arg, actor, request, *, purpose):
        assert len([m for m in request.messages if m.content == "Earlier turn"]) == 0
        return ChatResponse(
            text="",
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
        json={
            "message": "Swap the opener",
            "history": [{"role": "user", "content": "Earlier turn"}],
        },
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["message"].startswith("Swapped slot 1")
    assert body["tool_calls"][0]["display_summary"].startswith("Swapped slot 1")
    assert body["assistant_message"]["content"].startswith("Swapped slot 1")

    history = client.get(
        f"/api/setbuilder/sets/{set_obj['id']}/agent/history",
        headers=auth_headers,
    ).json()
    assert [m["role"] for m in history["messages"]] == ["user", "assistant"]
    assert history["messages"][0]["content"] == "Swap the opener"
    assert history["messages"][1]["display_summary"].startswith("Swapped slot 1")


def test_agent_chat_rolls_back_all_work_when_later_tool_fails(
    monkeypatch, client, auth_headers, db
):
    from app.models.set import SetSlot

    set_obj = _mk_set(client, auth_headers)
    _mk_pool(db, set_obj["id"])
    built = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/build",
        json={"confirmed": True},
        headers=auth_headers,
    ).json()
    first, second, locked = built["slots"][0], built["slots"][1], built["slots"][2]
    locked_slot = db.get(SetSlot, locked["id"])
    locked_slot.locked = True
    db.commit()

    original_track_ids = [
        track_id
        for (track_id,) in (
            db.query(SetSlot.track_id)
            .filter(SetSlot.set_id == set_obj["id"])
            .order_by(SetSlot.position.asc())
            .all()
        )
    ]

    async def fake_dispatch(*args, **kwargs):
        return ChatResponse(
            text="",
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(
                    id="swap-1",
                    name="swap_slots",
                    input={
                        "slot_a_id": first["id"],
                        "slot_b_id": second["id"],
                        "rationale": "Try the better opener.",
                    },
                ),
                ToolCall(
                    id="remove-1",
                    name="remove_slot",
                    input={
                        "slot_id": locked["id"],
                        "rationale": "Remove the locked slot.",
                    },
                ),
            ],
        )

    monkeypatch.setattr("app.services.setbuilder.pass2_agent.Gateway.dispatch", fake_dispatch)

    resp = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/agent/chat",
        json={"message": "Swap first, then remove locked"},
        headers=auth_headers,
    )

    assert resp.status_code == 400, resp.json()
    db.expire_all()
    current_track_ids = [
        track_id
        for (track_id,) in (
            db.query(SetSlot.track_id)
            .filter(SetSlot.set_id == set_obj["id"])
            .order_by(SetSlot.position.asc())
            .all()
        )
    ]
    assert current_track_ids == original_track_ids

    history = client.get(
        f"/api/setbuilder/sets/{set_obj['id']}/agent/history",
        headers=auth_headers,
    ).json()
    assert history["messages"] == []


def test_agent_history_owner_isolation(client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)

    from app.models.user import User
    from app.services.auth import create_access_token, get_password_hash

    other = User(username="agentother", password_hash=get_password_hash("password1234"), role="dj")
    db.add(other)
    db.commit()
    token = create_access_token(data={"sub": other.username, "tv": other.token_version})
    other_headers = {"Authorization": f"Bearer {token}"}

    resp = client.get(
        f"/api/setbuilder/sets/{set_obj['id']}/agent/history",
        headers=other_headers,
    )

    assert resp.status_code == 404
