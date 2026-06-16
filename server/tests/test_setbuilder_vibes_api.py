"""API-boundary tests for WrzDJSet pool-vibe endpoints (issue #391)."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.track_vibe import TrackVibe, TrackVibeOverride
from app.models.user import User
from app.services.llm.base import ChatResponse, ToolCall
from app.services.llm.exceptions import NoLlmConfigured, ProviderUnavailable
from app.services.setbuilder import vibe_resolver
from app.services.setbuilder.vibe_enrichment import PROMPT_VERSION, SCHEMA_VERSION

DISPATCH_TARGET = "app.services.setbuilder.vibe_enrichment.Gateway.dispatch"
NO_LLM_DETAIL = "No AI connector configured — connect one in Settings → AI."


@pytest.fixture
def set_id(client: TestClient, auth_headers: dict) -> int:
    resp = client.post("/api/setbuilder/sets", json={"name": "Vibe Set"}, headers=auth_headers)
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.fixture
def other_dj_headers(client: TestClient, db: Session) -> dict:
    from app.services.auth import get_password_hash

    user = User(username="otherdj", password_hash=get_password_hash("otherpassword1"), role="dj")
    db.add(user)
    db.commit()
    resp = client.post(
        "/api/auth/login", data={"username": "otherdj", "password": "otherpassword1"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _seed_pool_tracks(db: Session, set_id: int, n: int) -> None:
    """Direct-model pool seeding — tracks get keys tidal:0..n-1."""
    src = SetPoolSource(set_id=set_id, kind="manual", external_ref=None, label="Manual")
    db.add(src)
    db.flush()
    for i in range(n):
        db.add(
            SetPoolTrack(
                set_id=set_id,
                source_id=src.id,
                track_id=f"tidal:{i}",
                title=f"Track {i}",
                artist=f"Artist {i}",
                dedupe_sig=f"sig{i:04d}",
            )
        )
    db.commit()


def _pool_track_id(db: Session, set_id: int, track_id: str = "tidal:0") -> int:
    row = (
        db.query(SetPoolTrack)
        .filter(SetPoolTrack.set_id == set_id, SetPoolTrack.track_id == track_id)
        .one()
    )
    return row.id


def _make_voters(db: Session, n: int) -> list[User]:
    from app.services.auth import get_password_hash

    pw = get_password_hash("password123")
    users = [User(username=f"vibe-voter-{i}", password_hash=pw, role="dj") for i in range(n)]
    db.add_all(users)
    db.commit()
    for user in users:
        db.refresh(user)
    return users


def _vote(
    db: Session,
    track_id: str,
    user_id: int,
    *,
    energy: int | None = None,
    mood: str | None = None,
    source: str = "explicit_edit",
) -> TrackVibeOverride:
    row = TrackVibeOverride(
        track_id=track_id,
        user_id=user_id,
        energy_override=energy,
        mood_override=mood,
        source=source,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _llm_vibe_row(track_id: str = "tidal:0", *, energy: int = 5, confidence: float = 0.8):
    return TrackVibe(
        track_id=track_id,
        energy=energy,
        mood="happy",
        confidence=confidence,
        llm_provider="anthropic_apikey",
        llm_model="claude-haiku-4-5",
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
    )


def _fake_response(batch_size: int, *, confidence: float = 0.8) -> ChatResponse:
    items = [
        {
            "index": i,
            "energy": 7,
            "mood": "euphoric",
            "era": "2010s",
            "sing_along": True,
            "dance_floor": True,
            "transitional_role": "peak",
            "confidence": confidence,
        }
        for i in range(batch_size)
    ]
    return ChatResponse(
        text="",
        tool_calls=[ToolCall(id="t1", name="submit_track_vibes", input={"tracks": items})],
        stop_reason="tool_use",
        model="claude-haiku-4-5",
        provider="anthropic_apikey",
    )


class TestVibesOwnership:
    def test_vibes_404_for_other_users_set(self, client, set_id, other_dj_headers):
        assert (
            client.get(
                f"/api/setbuilder/sets/{set_id}/pool/vibes", headers=other_dj_headers
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/setbuilder/sets/{set_id}/pool/vibes/enrich", headers=other_dj_headers
            ).status_code
            == 404
        )

    def test_vibes_require_auth(self, client, set_id):
        assert client.get(f"/api/setbuilder/sets/{set_id}/pool/vibes").status_code == 401
        assert client.post(f"/api/setbuilder/sets/{set_id}/pool/vibes/enrich").status_code == 401


class TestGetPoolVibes:
    def test_empty_pool(self, client, auth_headers, set_id):
        resp = client.get(f"/api/setbuilder/sets/{set_id}/pool/vibes", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {"tracks": []}

    def test_no_vibe_data_all_tiers_null(self, client, db, auth_headers, set_id):
        _seed_pool_tracks(db, set_id, 2)
        resp = client.get(f"/api/setbuilder/sets/{set_id}/pool/vibes", headers=auth_headers)
        assert resp.status_code == 200
        tracks = resp.json()["tracks"]
        assert len(tracks) == 2
        assert [t["vibe_key"] for t in tracks] == ["tidal:0", "tidal:1"]
        for t in tracks:
            assert t["own"] is None
            assert t["community"] is None
            assert t["llm"] is None
            assert t["resolved"] == {
                "energy": None,
                "energy_source": None,
                "mood": None,
                "mood_source": None,
            }

    def test_own_override_precedence_over_llm(self, client, db, auth_headers, set_id, test_user):
        _seed_pool_tracks(db, set_id, 1)
        db.add(_llm_vibe_row("tidal:0", energy=5, confidence=0.8))
        db.add(
            TrackVibeOverride(
                track_id="tidal:0",
                user_id=test_user.id,
                energy_override=9,
                mood_override=None,
                source="explicit_edit",
            )
        )
        db.commit()

        resp = client.get(f"/api/setbuilder/sets/{set_id}/pool/vibes", headers=auth_headers)
        assert resp.status_code == 200
        (track,) = resp.json()["tracks"]
        assert track["own"] == {"energy": 9, "mood": None}
        assert track["resolved"]["energy"] == 9
        assert track["resolved"]["energy_source"] == "own"
        # mood has no own/community value — cascades to the LLM tier
        assert track["resolved"]["mood"] == "happy"
        assert track["resolved"]["mood_source"] == "llm"
        llm = track["llm"]
        assert llm is not None
        assert llm["energy"] == 5
        assert llm["confidence"] == 0.8
        assert llm["low_confidence"] is False
        assert llm["llm_provider"] == "anthropic_apikey"
        assert llm["llm_model"] == "claude-haiku-4-5"


class TestWritePoolVibes:
    def test_openapi_documents_pool_vibe_write_contract(self, client):
        schema = client.app.openapi()
        override = schema["components"]["schemas"]["PoolVibeOverrideIn"]

        assert override["minProperties"] == 1
        any_of = override.get("anyOf") or override.get("allOf", [{}])[0].get("anyOf", [])
        required_sets = {tuple(item["required"]) for item in any_of}
        assert ("energy",) in required_sets
        assert ("mood",) in required_sets

        responses = schema["paths"][
            "/api/setbuilder/sets/{set_id}/pool/vibes/{pool_track_id}/agree"
        ]["post"]["responses"]
        assert responses["400"]["description"] == (
            "No non-own vibe signal available for this pool track."
        )

    def test_agree_upvotes_consensus_without_own_override(
        self, client, db, auth_headers, set_id, test_user
    ):
        _seed_pool_tracks(db, set_id, 1)
        pool_track_id = _pool_track_id(db, set_id)
        for voter in _make_voters(db, 3):
            _vote(db, "tidal:0", voter.id, energy=7, mood="dark")

        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/vibes/{pool_track_id}/agree",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        body = resp.json()
        (track,) = body["tracks"]
        assert track["own"] is None
        assert track["community"] == {"energy": 7, "mood": "dark", "sample_size": 3}
        assert track["resolved"] == {
            "energy": 7,
            "energy_source": "community",
            "mood": "dark",
            "mood_source": "community",
        }

        row = (
            db.query(TrackVibeOverride)
            .filter(
                TrackVibeOverride.user_id == test_user.id,
                TrackVibeOverride.track_id == "tidal:0",
            )
            .one()
        )
        assert row.source == "upvote"
        assert row.energy_override == 7
        assert row.mood_override == "dark"
        assert row.energy_was is None
        assert row.mood_was is None

    def test_agree_uses_targeted_pre_write_lookup(
        self, client, db, auth_headers, set_id, test_user
    ):
        _seed_pool_tracks(db, set_id, 3)
        pool_track_id = _pool_track_id(db, set_id)
        for voter in _make_voters(db, 3):
            _vote(db, "tidal:0", voter.id, energy=7, mood="dark")

        with patch(
            "app.api.setbuilder.vibe_resolver.build_pool_vibe_states",
            wraps=vibe_resolver.build_pool_vibe_states,
        ) as build_states:
            resp = client.post(
                f"/api/setbuilder/sets/{set_id}/pool/vibes/{pool_track_id}/agree",
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert build_states.call_count == 1

    def test_agree_rejects_track_with_no_vibe_to_upvote(self, client, db, auth_headers, set_id):
        _seed_pool_tracks(db, set_id, 1)
        pool_track_id = _pool_track_id(db, set_id)

        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/vibes/{pool_track_id}/agree",
            headers=auth_headers,
        )

        assert resp.status_code == 400
        assert resp.json()["detail"] == "No vibe available to agree with"
        assert db.query(TrackVibeOverride).count() == 0

    def test_tweak_writes_explicit_override_with_previous_resolved_capture(
        self, client, db, auth_headers, set_id, test_user
    ):
        _seed_pool_tracks(db, set_id, 1)
        pool_track_id = _pool_track_id(db, set_id)
        llm = _llm_vibe_row("tidal:0", energy=5, confidence=0.8)
        db.add(llm)
        db.commit()
        db.refresh(llm)

        resp = client.patch(
            f"/api/setbuilder/sets/{set_id}/pool/vibes/{pool_track_id}/override",
            json={"energy": 8, "mood": "dark"},
            headers=auth_headers,
        )

        assert resp.status_code == 200
        (track,) = resp.json()["tracks"]
        assert track["own"] == {"energy": 8, "mood": "dark"}
        assert track["resolved"] == {
            "energy": 8,
            "energy_source": "own",
            "mood": "dark",
            "mood_source": "own",
        }

        row = (
            db.query(TrackVibeOverride)
            .filter(
                TrackVibeOverride.user_id == test_user.id,
                TrackVibeOverride.track_id == "tidal:0",
            )
            .one()
        )
        assert row.source == "explicit_edit"
        assert row.energy_override == 8
        assert row.mood_override == "dark"
        assert row.energy_was == 5
        assert row.mood_was == "happy"
        assert row.overridden_from_vibe_id == llm.id

    def test_tweak_carries_forward_omitted_fields_from_latest_vote(
        self, client, db, auth_headers, set_id, test_user
    ):
        _seed_pool_tracks(db, set_id, 1)
        pool_track_id = _pool_track_id(db, set_id)
        _vote(db, "tidal:0", test_user.id, energy=6, mood="dark", source="explicit_edit")

        resp = client.patch(
            f"/api/setbuilder/sets/{set_id}/pool/vibes/{pool_track_id}/override",
            json={"energy": 9},
            headers=auth_headers,
        )

        assert resp.status_code == 200
        rows = (
            db.query(TrackVibeOverride)
            .filter(
                TrackVibeOverride.user_id == test_user.id,
                TrackVibeOverride.track_id == "tidal:0",
            )
            .order_by(TrackVibeOverride.id)
            .all()
        )
        assert len(rows) == 2
        assert rows[-1].source == "explicit_edit"
        assert rows[-1].energy_override == 9
        assert rows[-1].mood_override == "dark"
        assert rows[-1].energy_was == 6
        assert rows[-1].mood_was == "dark"


class TestEnrichPoolVibes:
    def test_enrich_end_to_end(self, client, db, auth_headers, set_id):
        _seed_pool_tracks(db, set_id, 2)
        mock = AsyncMock(return_value=_fake_response(2))
        with patch(DISPATCH_TARGET, new=mock):
            resp = client.post(
                f"/api/setbuilder/sets/{set_id}/pool/vibes/enrich", headers=auth_headers
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["enriched"] == 2
        assert body["cached"] == 0
        assert body["failed"] == 0
        assert body["llm_calls"] == 1
        assert mock.await_count == 1
        tracks = body["vibes"]["tracks"]
        assert len(tracks) == 2
        for t in tracks:
            llm = t["llm"]
            assert llm is not None
            assert llm["llm_provider"] == "anthropic_apikey"
            assert llm["llm_model"] == "claude-haiku-4-5"
            assert llm["low_confidence"] is False
            assert t["resolved"]["energy_source"] == "llm"

    def test_enrich_low_confidence_flagged(self, client, db, auth_headers, set_id):
        _seed_pool_tracks(db, set_id, 1)
        with patch(DISPATCH_TARGET, new=AsyncMock(return_value=_fake_response(1, confidence=0.2))):
            resp = client.post(
                f"/api/setbuilder/sets/{set_id}/pool/vibes/enrich", headers=auth_headers
            )
        assert resp.status_code == 200
        (track,) = resp.json()["vibes"]["tracks"]
        assert track["llm"]["confidence"] == 0.2
        assert track["llm"]["low_confidence"] is True

    def test_enrich_no_llm_configured_400(self, client, db, auth_headers, set_id):
        _seed_pool_tracks(db, set_id, 1)
        with patch(DISPATCH_TARGET, new=AsyncMock(side_effect=NoLlmConfigured("none"))):
            resp = client.post(
                f"/api/setbuilder/sets/{set_id}/pool/vibes/enrich", headers=auth_headers
            )
        assert resp.status_code == 400
        assert resp.json()["detail"] == NO_LLM_DETAIL

    def test_enrich_provider_failure_returns_counts(self, client, db, auth_headers, set_id):
        _seed_pool_tracks(db, set_id, 2)
        with patch(
            DISPATCH_TARGET,
            new=AsyncMock(side_effect=ProviderUnavailable("timeout")),
        ):
            resp = client.post(
                f"/api/setbuilder/sets/{set_id}/pool/vibes/enrich", headers=auth_headers
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["enriched"] == 0
        assert body["failed"] == 2
        assert body["llm_calls"] == 1
        assert body["cached"] == 0
        tracks = body["vibes"]["tracks"]
        assert len(tracks) == 2
        for t in tracks:
            assert t["llm"] is None

    def test_second_run_fully_cached(self, client, db, auth_headers, set_id):
        _seed_pool_tracks(db, set_id, 2)
        with patch(DISPATCH_TARGET, new=AsyncMock(return_value=_fake_response(2))):
            first = client.post(
                f"/api/setbuilder/sets/{set_id}/pool/vibes/enrich", headers=auth_headers
            )
        assert first.status_code == 200
        assert first.json()["enriched"] == 2

        mock = AsyncMock(return_value=_fake_response(2))
        with patch(DISPATCH_TARGET, new=mock):
            second = client.post(
                f"/api/setbuilder/sets/{set_id}/pool/vibes/enrich", headers=auth_headers
            )
        assert second.status_code == 200
        body = second.json()
        assert body["cached"] == 2
        assert body["enriched"] == 0
        assert body["llm_calls"] == 0
        mock.assert_not_awaited()
