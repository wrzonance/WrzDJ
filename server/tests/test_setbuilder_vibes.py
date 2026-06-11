"""Tests for TrackVibe LLM enrichment + community consensus + resolver (issue #391)."""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.set import Set
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.track_vibe import TrackVibe
from app.models.user import User
from app.services.llm.base import ChatRequest, ChatResponse, ToolCall
from app.services.llm.exceptions import NoLlmConfigured, ProviderUnavailable
from app.services.setbuilder.vibe_enrichment import (
    PROMPT_VERSION,
    SCHEMA_VERSION,
    enrich_pool_vibes,
)
from app.services.system_settings import get_system_settings, update_system_settings


class TestVibeConsensusSettings:
    def test_defaults(self, db):
        s = get_system_settings(db)
        assert s.vibe_consensus_min_sample == 3
        assert s.vibe_consensus_max_stddev == 1.5

    def test_update(self, db):
        s = update_system_settings(db, vibe_consensus_min_sample=5, vibe_consensus_max_stddev=2.0)
        assert s.vibe_consensus_min_sample == 5
        assert s.vibe_consensus_max_stddev == 2.0

    def test_admin_patch_endpoint(self, client, admin_headers):
        resp = client.patch(
            "/api/admin/settings",
            json={"vibe_consensus_min_sample": 4, "vibe_consensus_max_stddev": 1.0},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["vibe_consensus_min_sample"] == 4
        assert body["vibe_consensus_max_stddev"] == 1.0

    def test_min_sample_bounds_rejected(self, client, admin_headers):
        for bad in (0, 101):
            resp = client.patch(
                "/api/admin/settings",
                json={"vibe_consensus_min_sample": bad},
                headers=admin_headers,
            )
            assert resp.status_code == 422

    def test_max_stddev_bounds_rejected(self, client, admin_headers):
        for bad in (0.0, 5.1):
            resp = client.patch(
                "/api/admin/settings",
                json={"vibe_consensus_max_stddev": bad},
                headers=admin_headers,
            )
            assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Batch LLM vibe enrichment (services/setbuilder/vibe_enrichment.py)
# ---------------------------------------------------------------------------

DISPATCH_TARGET = "app.services.setbuilder.vibe_enrichment.Gateway.dispatch"


def _seed_pool(db, owner_id: int, n: int) -> Set:
    s = Set(owner_id=owner_id, name="Vibe Set")
    db.add(s)
    db.flush()
    src = SetPoolSource(set_id=s.id, kind="manual", external_ref=None, label="Manual")
    db.add(src)
    db.flush()
    for i in range(n):
        db.add(
            SetPoolTrack(
                set_id=s.id,
                source_id=src.id,
                track_id=f"tidal:{i}",
                title=f"Track {i}",
                artist=f"Artist {i}",
                dedupe_sig=f"sig{i:04d}",
            )
        )
    db.commit()
    db.refresh(s)
    return s


def _fake_response(
    batch_size: int, *, provider="anthropic_apikey", model="claude-haiku-4-5"
) -> ChatResponse:
    items = [
        {
            "index": i,
            "energy": 7,
            "mood": "euphoric",
            "era": "2010s",
            "sing_along": True,
            "dance_floor": True,
            "transitional_role": "peak",
            "confidence": 0.8,
        }
        for i in range(batch_size)
    ]
    return ChatResponse(
        text="",
        tool_calls=[ToolCall(id="t1", name="submit_track_vibes", input={"tracks": items})],
        stop_reason="tool_use",
        model=model,
        provider=provider,
    )


def _dispatch_side_effect(*args, **kwargs) -> ChatResponse:
    """Build a fake response sized to the dispatched batch's track-line count."""
    request: ChatRequest = args[2]
    user_msg = next(m for m in request.messages if m.role == "user")
    n_lines = len(str(user_msg.content).strip().splitlines())
    return _fake_response(n_lines)


class TestVibeEnrichment:
    @pytest.mark.asyncio
    async def test_100_tracks_costs_5_calls(self, db, test_user):
        s = _seed_pool(db, test_user.id, 100)
        mock = AsyncMock(side_effect=_dispatch_side_effect)
        with patch(DISPATCH_TARGET, new=mock):
            stats = await enrich_pool_vibes(db, test_user, s)
        assert stats.llm_calls == 5
        assert stats.enriched == 100
        assert stats.failed == 0
        assert mock.await_count == 5
        assert db.query(TrackVibe).count() == 100

    @pytest.mark.asyncio
    async def test_second_run_fully_cached_even_for_other_dj(self, db, test_user):
        s1 = _seed_pool(db, test_user.id, 100)
        with patch(DISPATCH_TARGET, new=AsyncMock(side_effect=_dispatch_side_effect)):
            await enrich_pool_vibes(db, test_user, s1)

        other = User(username="otherdj", password_hash="x", role="dj")
        db.add(other)
        db.commit()
        db.refresh(other)
        s2 = _seed_pool(db, other.id, 100)  # same track_ids tidal:0..99

        mock = AsyncMock(side_effect=_dispatch_side_effect)
        with patch(DISPATCH_TARGET, new=mock):
            stats = await enrich_pool_vibes(db, other, s2)
        assert stats.llm_calls == 0
        assert stats.cached == 100
        assert stats.enriched == 0
        mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_prompt_version_bump_reenriches(self, db, test_user):
        s = _seed_pool(db, test_user.id, 1)
        db.add(
            TrackVibe(
                track_id="tidal:0",
                energy=5,
                llm_provider="anthropic_apikey",
                llm_model="claude-haiku-4-5",
                prompt_version="v0",
                schema_version=SCHEMA_VERSION,
            )
        )
        db.commit()

        mock = AsyncMock(side_effect=_dispatch_side_effect)
        with patch(DISPATCH_TARGET, new=mock):
            stats = await enrich_pool_vibes(db, test_user, s)
        assert mock.await_count == 1
        assert stats.enriched == 1
        rows = db.query(TrackVibe).filter(TrackVibe.track_id == "tidal:0").all()
        assert {r.prompt_version for r in rows} == {"v0", PROMPT_VERSION}
        old = next(r for r in rows if r.prompt_version == "v0")
        assert old.energy == 5  # old row untouched

    @pytest.mark.asyncio
    async def test_malformed_items_handled(self, db, test_user):
        s = _seed_pool(db, test_user.id, 3)
        items = [
            {
                "index": 0,
                "energy": 99,  # clamp -> 10
                "confidence": 1.7,  # clamp -> 1.0
                "transitional_role": "banger",  # not in enum -> None
                "mood": "dark",
                "era": "90s",
                "sing_along": "yes",  # not a bool -> None
                "dance_floor": True,
            },
            {
                "index": 1,
                "energy": 7,
                "mood": "euphoric",
                "era": "2010s",
                "sing_along": True,
                "dance_floor": True,
                "transitional_role": "peak",
                "confidence": 0.8,
            },
            {"index": 7, "energy": 5, "confidence": 0.5},  # out-of-range -> ignored
        ]
        response = ChatResponse(
            text="",
            tool_calls=[ToolCall(id="t1", name="submit_track_vibes", input={"tracks": items})],
            stop_reason="tool_use",
            model="claude-haiku-4-5",
            provider="anthropic_apikey",
        )
        with patch(DISPATCH_TARGET, new=AsyncMock(return_value=response)):
            stats = await enrich_pool_vibes(db, test_user, s)
        assert stats.enriched == 2
        assert stats.failed == 1  # track 2 had no parsed entry
        row0 = db.query(TrackVibe).filter(TrackVibe.track_id == "tidal:0").one()
        assert row0.energy == 10
        assert row0.confidence == 1.0
        assert row0.transitional_role is None
        assert row0.sing_along is None
        assert row0.dance_floor is True
        assert row0.mood == "dark"
        row1 = db.query(TrackVibe).filter(TrackVibe.track_id == "tidal:1").one()
        assert row1.energy == 7
        assert db.query(TrackVibe).filter(TrackVibe.track_id == "tidal:2").count() == 0

    @pytest.mark.asyncio
    async def test_llm_error_marks_remaining_failed(self, db, test_user):
        s = _seed_pool(db, test_user.id, 40)
        mock = AsyncMock(side_effect=[_fake_response(20), ProviderUnavailable("down")])
        with patch(DISPATCH_TARGET, new=mock):
            stats = await enrich_pool_vibes(db, test_user, s)
        assert stats.enriched == 20
        assert stats.failed == 20
        assert stats.llm_calls == 2
        assert db.query(TrackVibe).count() == 20

    @pytest.mark.asyncio
    async def test_no_llm_configured_propagates(self, db, test_user):
        s = _seed_pool(db, test_user.id, 1)
        with patch(DISPATCH_TARGET, new=AsyncMock(side_effect=NoLlmConfigured("none"))):
            with pytest.raises(NoLlmConfigured):
                await enrich_pool_vibes(db, test_user, s)

    @pytest.mark.asyncio
    async def test_track_without_track_id_uses_sig_key(self, db, test_user):
        s = Set(owner_id=test_user.id, name="Vibe Set")
        db.add(s)
        db.flush()
        src = SetPoolSource(set_id=s.id, kind="manual", external_ref=None, label="Manual")
        db.add(src)
        db.flush()
        db.add(
            SetPoolTrack(
                set_id=s.id,
                source_id=src.id,
                track_id=None,
                title="Track X",
                artist="Artist X",
                dedupe_sig="sigx001",
            )
        )
        db.commit()
        db.refresh(s)

        with patch(DISPATCH_TARGET, new=AsyncMock(side_effect=_dispatch_side_effect)):
            stats = await enrich_pool_vibes(db, test_user, s)
        assert stats.enriched == 1
        row = db.query(TrackVibe).one()
        assert row.track_id == "sig:sigx001"

    @pytest.mark.asyncio
    async def test_provider_model_fallback_unknown(self, db, test_user):
        s = _seed_pool(db, test_user.id, 1)
        response = _fake_response(1, provider=None, model=None)
        with patch(DISPATCH_TARGET, new=AsyncMock(return_value=response)):
            stats = await enrich_pool_vibes(db, test_user, s)
        assert stats.enriched == 1
        row = db.query(TrackVibe).one()
        assert row.llm_provider == "unknown"
        assert row.llm_model == "unknown"
