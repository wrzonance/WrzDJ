"""Tests for TrackVibe LLM enrichment + community consensus + resolver (issue #391)."""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.set import Set
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.track_vibe import TrackVibe, TrackVibeOverride
from app.models.user import User
from app.services.auth import get_password_hash
from app.services.llm.base import ChatRequest, ChatResponse, ToolCall
from app.services.llm.exceptions import NoLlmConfigured, ProviderUnavailable
from app.services.setbuilder.community_vibe import CommunityVibe, community_consensus
from app.services.setbuilder.vibe_enrichment import (
    PROMPT_VERSION,
    SCHEMA_VERSION,
    enrich_pool_vibes,
)
from app.services.setbuilder.vibe_resolver import (
    OwnVibe,
    ResolvedVibe,
    build_pool_vibe_states,
    is_low_confidence,
    resolve_vibe,
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
CACHED_KEYS_TARGET = "app.services.setbuilder.vibe_enrichment._cached_keys"


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
        # Pin the dispatch contract: forced tool, system prompt, token cap, purpose.
        args, kwargs = mock.await_args
        request: ChatRequest = args[2]
        assert request.force_tool == "submit_track_vibes"
        assert request.system
        assert request.max_tokens == 4096
        assert kwargs["purpose"] == "vibe_enrichment"

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
        s = _seed_pool(db, test_user.id, 4)
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
            {
                "index": 2,
                "energy": 5,
                "confidence": 0.5,
                "transitional_role": ["peak"],  # unhashable (list) -> None, must not raise
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
        assert stats.enriched == 3
        assert stats.failed == 1  # track 3 had no parsed entry
        row0 = db.query(TrackVibe).filter(TrackVibe.track_id == "tidal:0").one()
        assert row0.energy == 10
        assert row0.confidence == 1.0
        assert row0.transitional_role is None
        assert row0.sing_along is None
        assert row0.dance_floor is True
        assert row0.mood == "dark"
        row1 = db.query(TrackVibe).filter(TrackVibe.track_id == "tidal:1").one()
        assert row1.energy == 7
        row2 = db.query(TrackVibe).filter(TrackVibe.track_id == "tidal:2").one()
        assert row2.transitional_role is None  # list role stored as None
        assert row2.energy == 5
        assert db.query(TrackVibe).filter(TrackVibe.track_id == "tidal:3").count() == 0

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
    async def test_commit_race_keeps_paid_rows_and_counts_conflict_cached(self, db, test_user):
        """IntegrityError on commit must not discard the batch's non-conflicting rows.

        Forces the race: a conflicting TrackVibe row exists for tidal:1 (same
        identity the service writes), but ``_cached_keys`` is patched to miss it
        on both the initial cache check and the pre-insert re-check — so the
        commit collides. The post-IntegrityError re-query (third call) delegates
        to the real helper, finds the winner, and only the still-missing rows
        are re-inserted.
        """
        from app.services.setbuilder.vibe_enrichment import _cached_keys as real_cached_keys

        s = _seed_pool(db, test_user.id, 3)
        db.add(
            TrackVibe(
                track_id="tidal:1",
                energy=3,
                llm_provider="anthropic_apikey",
                llm_model="claude-haiku-4-5",
                prompt_version=PROMPT_VERSION,
                schema_version=SCHEMA_VERSION,
            )
        )
        db.commit()

        calls: list[int] = []

        def fake_cached_keys(db_arg, keys):
            calls.append(1)
            if len(calls) <= 2:  # initial cache check + pre-insert re-check miss the winner
                return set()
            return real_cached_keys(db_arg, keys)  # post-IntegrityError re-query is real

        with (
            patch(DISPATCH_TARGET, new=AsyncMock(side_effect=_dispatch_side_effect)),
            patch(CACHED_KEYS_TARGET, side_effect=fake_cached_keys),
        ):
            stats = await enrich_pool_vibes(db, test_user, s)

        assert stats.enriched == 2  # tidal:0 + tidal:2 survive the lost race
        assert stats.cached == 1  # the conflicting tidal:1 counts as cached
        assert stats.failed == 0
        assert len(calls) == 3
        for key in ("tidal:0", "tidal:2"):
            assert db.query(TrackVibe).filter(TrackVibe.track_id == key).count() == 1
        row1 = db.query(TrackVibe).filter(TrackVibe.track_id == "tidal:1").one()
        assert row1.energy == 3  # pre-existing winner untouched

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


# ---------------------------------------------------------------------------
# Community vibe consensus (services/setbuilder/community_vibe.py)
# ---------------------------------------------------------------------------


def _make_users(db, n: int, prefix: str = "voter") -> list[User]:
    pw = get_password_hash("password123")  # hash once — bcrypt is slow
    users = [User(username=f"{prefix}{i}", password_hash=pw, role="dj") for i in range(n)]
    db.add_all(users)
    db.commit()
    for u in users:
        db.refresh(u)
    return users


def _vote(
    db,
    track_id: str,
    user_id: int,
    *,
    energy: int | None = None,
    mood: str | None = None,
) -> TrackVibeOverride:
    row = TrackVibeOverride(
        track_id=track_id,
        user_id=user_id,
        energy_override=energy,
        mood_override=mood,
        source="explicit_edit",
    )
    db.add(row)
    db.commit()
    return row


class TestCommunityConsensus:
    def test_consensus_requires_min_sample(self, db):
        users = _make_users(db, 3)
        _vote(db, "tidal:1", users[0].id, energy=7)
        _vote(db, "tidal:1", users[1].id, energy=7)
        result = community_consensus(db, ["tidal:1"], min_sample=3, max_stddev=1.5)
        assert "tidal:1" not in result

        _vote(db, "tidal:1", users[2].id, energy=8)
        result = community_consensus(db, ["tidal:1"], min_sample=3, max_stddev=1.5)
        assert result["tidal:1"].energy == 7  # fmean 7.33 rounds to 7
        assert result["tidal:1"].sample_size == 3

    def test_consensus_rejected_on_high_stddev(self, db):
        users = _make_users(db, 3)
        for user, energy in zip(users, (1, 5, 10), strict=True):
            _vote(db, "tidal:1", user.id, energy=energy)
        # pstdev([1, 5, 10]) ~= 3.68 >= 1.5 — too scattered; no moods either.
        result = community_consensus(db, ["tidal:1"], min_sample=3, max_stddev=1.5)
        assert "tidal:1" not in result

    def test_latest_vote_per_user_wins(self, db):
        users = _make_users(db, 3)
        _vote(db, "tidal:1", users[0].id, energy=2)
        _vote(db, "tidal:1", users[0].id, energy=8)  # supersedes the 2
        _vote(db, "tidal:1", users[1].id, energy=8)
        _vote(db, "tidal:1", users[2].id, energy=8)
        result = community_consensus(db, ["tidal:1"], min_sample=3, max_stddev=1.5)
        assert result["tidal:1"].energy == 8
        assert result["tidal:1"].sample_size == 3

    def test_mood_majority(self, db):
        users = _make_users(db, 3)
        for user, mood in zip(users, ("dark", "dark", "euphoric"), strict=True):
            _vote(db, "tidal:1", user.id, mood=mood)
        result = community_consensus(db, ["tidal:1"], min_sample=3, max_stddev=1.5)
        assert result["tidal:1"].mood == "dark"  # 2/3 is a strict majority

        for user, mood in zip(users, ("dark", "euphoric", "upbeat"), strict=True):
            _vote(db, "tidal:2", user.id, mood=mood)
        result = community_consensus(db, ["tidal:2"], min_sample=3, max_stddev=1.5)
        assert "tidal:2" not in result  # three-way split: no strict majority

    def test_thresholds_are_tunable(self, db):
        users = _make_users(db, 2)
        _vote(db, "tidal:1", users[0].id, energy=7, mood="dark")
        _vote(db, "tidal:1", users[1].id, energy=7, mood="dark")
        result = community_consensus(db, ["tidal:1"], min_sample=2, max_stddev=1.5)
        assert result["tidal:1"].energy == 7
        assert result["tidal:1"].mood == "dark"
        assert result["tidal:1"].sample_size == 2

    def test_energy_and_mood_independent(self, db):
        users = _make_users(db, 3)
        _vote(db, "tidal:1", users[0].id, energy=7, mood="dark")
        _vote(db, "tidal:1", users[1].id, energy=7, mood="dark")
        _vote(db, "tidal:1", users[2].id, mood="dark")  # no energy opinion
        result = community_consensus(db, ["tidal:1"], min_sample=3, max_stddev=1.5)
        vibe = result["tidal:1"]
        assert vibe.mood == "dark"
        assert vibe.energy is None  # only 2 energy votes < min_sample
        assert vibe.sample_size == 3


# ---------------------------------------------------------------------------
# Three-tier precedence resolver (services/setbuilder/vibe_resolver.py)
# ---------------------------------------------------------------------------


def _llm_vibe(
    track_id: str = "tidal:0",
    *,
    energy: int | None = None,
    mood: str | None = None,
    confidence: float | None = None,
    provider: str = "anthropic_apikey",
    prompt_version: str = PROMPT_VERSION,
) -> TrackVibe:
    return TrackVibe(
        track_id=track_id,
        energy=energy,
        mood=mood,
        confidence=confidence,
        llm_provider=provider,
        llm_model="claude-haiku-4-5",
        prompt_version=prompt_version,
        schema_version=SCHEMA_VERSION,
    )


class TestVibeResolver:
    def test_own_override_wins(self):
        own = OwnVibe(energy=9, mood="gritty")
        community = CommunityVibe(energy=5, mood="dark", sample_size=4)
        llm = _llm_vibe(energy=3, mood="happy", confidence=0.9)
        resolved = resolve_vibe(own, community, llm)
        assert (resolved.energy, resolved.energy_source) == (9, "own")
        assert (resolved.mood, resolved.mood_source) == ("gritty", "own")

    def test_community_beats_llm(self):
        community = CommunityVibe(energy=5, mood="dark", sample_size=4)
        llm = _llm_vibe(energy=3, mood="happy", confidence=0.9)
        resolved = resolve_vibe(None, community, llm)
        assert (resolved.energy, resolved.energy_source) == (5, "community")
        assert (resolved.mood, resolved.mood_source) == ("dark", "community")

    def test_llm_fallback(self):
        llm = _llm_vibe(energy=3, mood="happy", confidence=0.9)
        resolved = resolve_vibe(None, None, llm)
        assert (resolved.energy, resolved.energy_source) == (3, "llm")
        assert (resolved.mood, resolved.mood_source) == ("happy", "llm")

    def test_no_tiers_resolves_none(self):
        assert resolve_vibe(None, None, None) == ResolvedVibe(None, None, None, None)

    def test_per_field_cascade(self):
        own = OwnVibe(energy=9, mood=None)
        community = CommunityVibe(energy=None, mood="dark", sample_size=3)
        llm = _llm_vibe(energy=4, mood="happy", confidence=0.9)
        resolved = resolve_vibe(own, community, llm)
        assert (resolved.energy, resolved.energy_source) == (9, "own")
        assert (resolved.mood, resolved.mood_source) == ("dark", "community")

    def test_low_confidence_flag(self):
        assert is_low_confidence(_llm_vibe(confidence=0.3)) is True
        assert is_low_confidence(_llm_vibe(confidence=0.5)) is False
        assert is_low_confidence(_llm_vibe(confidence=0.9)) is False
        assert is_low_confidence(_llm_vibe(confidence=None)) is True

    def test_build_pool_vibe_states_end_to_end(self, db, test_user):
        s = _seed_pool(db, test_user.id, 1)  # one pool track, key "tidal:0"
        db.add(_llm_vibe(energy=5, mood="happy", confidence=0.8))
        voters = _make_users(db, 3)
        for voter, energy in zip(voters, (7, 7, 8), strict=True):
            _vote(db, "tidal:0", voter.id, energy=energy, mood="dark")
        _vote(db, "tidal:0", test_user.id, energy=9)  # own override, no mood
        db.commit()

        states = build_pool_vibe_states(db, test_user, s)
        assert len(states) == 1
        state = states[0]
        assert state.vibe_key == "tidal:0"
        assert state.own == OwnVibe(energy=9, mood=None)
        # Own vote excluded from community: fmean(7,7,8) = 7.33 -> 7, sample 3.
        assert state.community == CommunityVibe(energy=7, mood="dark", sample_size=3)
        assert state.llm is not None
        assert state.llm.energy == 5
        assert state.resolved == ResolvedVibe(
            energy=9, energy_source="own", mood="dark", mood_source="community"
        )

    def test_llm_tier_ignores_stale_prompt_version(self, db, test_user):
        s = _seed_pool(db, test_user.id, 1)
        db.add(_llm_vibe(energy=5, mood="happy", confidence=0.8, prompt_version="v0"))
        db.commit()

        states = build_pool_vibe_states(db, test_user, s)
        assert len(states) == 1
        assert states[0].llm is None
        assert states[0].resolved == ResolvedVibe(None, None, None, None)

    def test_llm_tier_newest_row_wins(self, db, test_user):
        s = _seed_pool(db, test_user.id, 1)
        db.add(_llm_vibe(energy=3, mood="dark", confidence=0.7, provider="openai_apikey"))
        db.commit()
        db.add(_llm_vibe(energy=6, mood="happy", confidence=0.8, provider="anthropic_apikey"))
        db.commit()

        states = build_pool_vibe_states(db, test_user, s)
        assert len(states) == 1
        assert states[0].llm is not None
        assert states[0].llm.energy == 6  # higher-id row wins
        assert (states[0].resolved.energy, states[0].resolved.energy_source) == (6, "llm")
