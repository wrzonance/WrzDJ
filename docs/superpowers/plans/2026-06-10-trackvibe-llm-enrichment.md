# TrackVibe LLM Enrichment + Community Vibe Display (issue #391) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Batch-enrich pool tracks with LLM-guessed vibe metadata (cached globally in `TrackVibe`), aggregate per-DJ `TrackVibeOverride` rows into a community consensus, and surface all three tiers (own → community → LLM) read-only in the pool panel with low-confidence flagging.

**Architecture:** The `TrackVibe` / `TrackVibeOverride` models and tables already exist (Phase 0 scaffold, migration 046) — no model changes needed there. We add: two SystemSettings threshold columns (migration 057), an additive `provider` field on `ChatResponse` populated by the gateway, three new service modules under `services/setbuilder/` (enrichment, community aggregation, precedence resolver), two owner-scoped endpoints on the setbuilder router, and a read-only three-tier UI strip in the PoolPanel.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic (backend), LLM Gateway (`Gateway.dispatch`, forced tool_use), Next.js/React + vanilla CSS (frontend), pytest + vitest.

**Worktree:** `/home/adam/github/WrzDJ/.worktrees/feat/issue-391` — branch `feat/issue-391`. NEVER commit to main.
**Python tools:** `/home/adam/github/WrzDJ/server/.venv/bin/{pytest,ruff,bandit,alembic}` run from `<worktree>/server`. Never pip install.
**DB:** dedicated `wrzdj_issue391` already at head 056 (`.env` at worktree root).

---

## Design decisions (document in PR body)

1. **`model_hint="fast"` deviation:** `ChatRequest` has no speed-tier concept — it has `model: str | None` which overrides the *connector's* configured `model_hint`. We dispatch with `model=None` so the DJ's connector-configured model is used. Adding a cross-provider "fast/smart" tier mapping would require per-adapter model tables (rejected as gateway refactoring, which the task forbids).
2. **Provider/model provenance:** `ChatResponse` did not surface which connector served a call. Minimal additive change: `ChatResponse.provider: str | None`, populated by the gateway's `_attempt` success path from `connector.connector_type` via `model_copy(update=...)`. No other gateway behavior changes.
3. **Vibe cache key:** `SetPoolTrack.track_id` is nullable. Fallback key is `f"sig:{dedupe_sig}"` (the normalized artist+title hash) — globally stable across sets/DJs, consistent with the namespaced free-form `track_id` convention.
4. **Cache-hit semantics:** any `TrackVibe` row matching `(track_id, prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION)` is a hit *regardless of provider/model* — that's what makes "second DJ pays zero" true even when DJs use different connectors. Bumping `PROMPT_VERSION` in code makes old rows non-matching → lazy re-enrichment. When multiple rows exist, the newest (highest id) wins at read time.
5. **`purpose="vibe_enrichment"`** for gateway call logging.
6. **Batch failure policy:** the first `LlmError` (other than the initial `NoLlmConfigured`, which maps to HTTP 400) marks all remaining tracks failed and stops — no provider hammering after a rate-limit/outage.
7. **Community consensus:** latest override row per `(track_id, user_id)` counts as that user's vote. Energy consensus: `count >= vibe_consensus_min_sample AND pstdev < vibe_consensus_max_stddev` → `round(mean)`. Mood consensus: most-common non-null mood where mood-vote count ≥ min_sample and strict majority (> 50%).
8. **`TrackVibeOverride` write UX is v1.1** — table already existed from Phase 0, so no new table needed; we add NO write endpoints (read path only).
9. **Low-confidence flag** computed backend-side (`confidence is None or < 0.5`) so the frontend stays dumb.

---

### Task 1: SystemSettings threshold columns + migration 057

**Files:**
- Modify: `server/app/models/system_settings.py`
- Create: `server/alembic/versions/057_add_vibe_consensus_settings.py`
- Modify: `server/app/services/system_settings.py`
- Modify: `server/app/schemas/system_settings.py`
- Modify: `server/app/api/admin.py` (PATCH /settings passthrough, ~line 264)
- Test: `server/tests/test_setbuilder_vibes.py` (new — settings section)

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_setbuilder_vibes.py`:

```python
"""Tests for TrackVibe LLM enrichment + community consensus + resolver (issue #391)."""

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/adam/github/WrzDJ/.worktrees/feat/issue-391/server && /home/adam/github/WrzDJ/server/.venv/bin/pytest tests/test_setbuilder_vibes.py -v --no-cov`
Expected: FAIL (AttributeError: vibe_consensus_min_sample)

- [ ] **Step 3: Implement**

In `server/app/models/system_settings.py` — add `Float` to the sqlalchemy import and append columns at the end of the class:

```python
    # Community vibe consensus gates (issue #391). Consensus over
    # TrackVibeOverride requires sample_size >= min_sample AND energy stddev
    # < max_stddev. Bounds enforced at the API layer.
    vibe_consensus_min_sample: Mapped[int] = mapped_column(
        Integer, default=3, server_default=text("3")
    )
    vibe_consensus_max_stddev: Mapped[float] = mapped_column(
        Float, default=1.5, server_default=text("1.5")
    )
```

Create `server/alembic/versions/057_add_vibe_consensus_settings.py`:

```python
"""Vibe consensus threshold settings (issue #391).

Revision ID: 057
Revises: 056
Create Date: 2026-06-10

Community consensus over track_vibe_overrides is gated on
sample_size >= vibe_consensus_min_sample AND energy stddev <
vibe_consensus_max_stddev. Both admin-tunable via PATCH /api/admin/settings.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "057"
down_revision: str | None = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "vibe_consensus_min_sample", sa.Integer(), nullable=False, server_default=sa.text("3")
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "vibe_consensus_max_stddev", sa.Float(), nullable=False, server_default=sa.text("1.5")
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "vibe_consensus_max_stddev")
    op.drop_column("system_settings", "vibe_consensus_min_sample")
```

In `server/app/services/system_settings.py` — add to `get_system_settings` defaults dict: `vibe_consensus_min_sample=3, vibe_consensus_max_stddev=1.5,`. Add params to `update_system_settings`:

```python
    vibe_consensus_min_sample: int | None = None,
    vibe_consensus_max_stddev: float | None = None,
```
and the corresponding `if ... is not None:` assignments before `db.commit()`.

In `server/app/schemas/system_settings.py` — `SystemSettingsOut` gains `vibe_consensus_min_sample: int` and `vibe_consensus_max_stddev: float`; `SystemSettingsUpdate` gains:

```python
    vibe_consensus_min_sample: int | None = Field(None, ge=1, le=100)
    vibe_consensus_max_stddev: float | None = Field(None, ge=0.1, le=5.0)
```

In `server/app/api/admin.py` PATCH `/settings` handler — pass both through to `update_system_settings(...)` like the existing fields.

- [ ] **Step 4: Run tests + alembic check**

Run: `cd <worktree>/server && /home/adam/github/WrzDJ/server/.venv/bin/pytest tests/test_setbuilder_vibes.py tests/test_admin.py -q --no-cov`
Expected: PASS
Run: `/home/adam/github/WrzDJ/server/.venv/bin/alembic upgrade head && /home/adam/github/WrzDJ/server/.venv/bin/alembic check`
Expected: "No new upgrade operations detected"

- [ ] **Step 5: Commit** — `feat(setbuilder): vibe consensus threshold settings (migration 057)`

---

### Task 2: ChatResponse.provider populated by the gateway

**Files:**
- Modify: `server/app/services/llm/base.py` (ChatResponse)
- Modify: `server/app/services/llm/gateway.py` (`_attempt` success path)
- Test: `server/tests/test_llm_gateway.py` (append one test)

- [ ] **Step 1: Write the failing test** (append to `test_llm_gateway.py`, reusing `_make_connector`, `_patch_chat`, `dj_user`, `gateway_request` fixtures):

```python
@pytest.mark.asyncio
async def test_dispatch_populates_provider_from_connector(db, dj_user, gateway_request):
    """#391 — vibe enrichment needs provider provenance on the response."""
    _make_connector(db, dj_user)
    fake_response = ChatResponse(
        text="ok", tool_calls=[], stop_reason="end_turn",
        usage=TokenUsage(prompt=1, completion=1), model="gpt-5-mini",
    )
    with _patch_chat(AsyncMock(return_value=fake_response)):
        resp = await Gateway.dispatch(db, dj_user, gateway_request, purpose="test")
    assert resp.provider == "openai_apikey"
    assert resp.model == "gpt-5-mini"
```

- [ ] **Step 2: Run to verify it fails** (`pytest tests/test_llm_gateway.py -k provider -v --no-cov`) — FAIL: ChatResponse has no field "provider".

- [ ] **Step 3: Implement.** In `base.py` `ChatResponse`, after `model`:

```python
    # The connector_type that served the call (e.g. "anthropic_apikey").
    # Populated by the gateway from the resolved connector — adapters leave it None.
    provider: str | None = None
```

In `gateway.py` `_attempt`, change the final `return response` to:

```python
    # Surface which connector served the call (issue #391 — vibe provenance).
    return response.model_copy(update={"provider": connector.connector_type})
```

- [ ] **Step 4: Run** `pytest tests/test_llm_gateway.py tests/test_llm_gateway_stream.py -q --no-cov` — PASS.
- [ ] **Step 5: Commit** — `feat(llm): surface serving connector_type as ChatResponse.provider`

---

### Task 3: vibe_enrichment service (batching, caching, defensive parsing)

**Files:**
- Create: `server/app/services/setbuilder/vibe_enrichment.py`
- Test: `server/tests/test_setbuilder_vibes.py` (append)

Service contract:

```python
PURPOSE = "vibe_enrichment"
PROMPT_VERSION = "v1"
SCHEMA_VERSION = "v1"
BATCH_SIZE = 20
MAX_TOKENS = 4096
TRANSITIONAL_ROLES = frozenset({"intro", "build", "peak", "cool", "any"})

def vibe_key(track: SetPoolTrack) -> str:
    """Global cache key — namespaced track_id, else the dedupe signature."""
    return track.track_id or f"sig:{track.dedupe_sig}"

@dataclass(frozen=True)
class VibeEnrichmentStats:
    enriched: int
    cached: int
    failed: int
    llm_calls: int

async def enrich_pool_vibes(db: Session, actor: User, set_obj: Set) -> VibeEnrichmentStats
```

Implementation outline (full code in the module):
- Load pool tracks, key them by `vibe_key` (dict de-dupes within the pool).
- `cached` = keys having a `TrackVibe` row with matching PROMPT_VERSION/SCHEMA_VERSION (any provider/model).
- Chunk missing keys into batches of `BATCH_SIZE`. For each batch: build a `ChatRequest` (system prompt + numbered track list user message + forced tool `submit_track_vibes`), `await Gateway.dispatch(db, actor, req, purpose=PURPOSE)`, increment `llm_calls`.
- `NoLlmConfigured` propagates (caller maps to 400). Any other `LlmError`: remaining tracks (current batch + later batches) count as failed; stop.
- Parse tool output defensively (`_parse_items`): index must be a valid int in range; energy int clamped 0–10 (floats rounded); confidence clamped 0.0–1.0; transitional_role must be in `TRANSITIONAL_ROLES` else None; mood/era truncated to 50 chars; sing_along/dance_floor only if actual bool. Tracks with no parsed entry count as failed.
- Insert `TrackVibe` rows with `llm_provider=response.provider or "unknown"`, `llm_model=response.model or "unknown"`. Re-check existing keys just before insert and wrap the per-batch commit in `try/except IntegrityError: db.rollback()` (concurrent-enrichment race → treat as cached).

Tool schema (forced tool_use, mirrors `recommendation/llm_client.py` precedent):

```python
VIBES_TOOL_NAME = "submit_track_vibes"
VIBES_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "tracks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "description": "Input track number"},
                    "energy": {"type": "integer", "minimum": 0, "maximum": 10},
                    "mood": {"type": "string", "description": "1-2 lowercase words"},
                    "era": {"type": "string", "description": "decade or scene era"},
                    "sing_along": {"type": "boolean"},
                    "dance_floor": {"type": "boolean"},
                    "transitional_role": {
                        "type": "string",
                        "enum": ["intro", "build", "peak", "cool", "any"],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["index", "energy", "confidence"],
            },
        }
    },
    "required": ["tracks"],
}
```

System prompt (verbatim):

```
You are a music-metadata expert annotating tracks for DJ set planning.

For each numbered track estimate:
- energy: integer 0-10 (0 = ambient/chill, 10 = peak-time mainstage intensity)
- mood: one or two lowercase words (e.g. "euphoric", "dark", "feel-good")
- era: release decade or scene era (e.g. "90s", "2010s", "classic house")
- sing_along: true if crowds commonly sing the hook out loud
- dance_floor: true if the track reliably keeps a dance floor moving
- transitional_role: where it fits in a set arc — "intro", "build", "peak", "cool", or "any"
- confidence: 0-1 — how certain you are you know this exact track
  (0.2 = guessing from the title, 0.9 = you know the track well)

Be honest with confidence: if you do not recognize a track, keep confidence
below 0.4 and infer from title/artist/genre conventions. Return one entry per
input track, matched by index.
```

User message: one line per track — `"{i}. {artist} — {title}"` plus ` ({genre}, {bpm:.0f} BPM)` parts when known.

Tests (mock `Gateway.dispatch` with `unittest.mock.patch("app.services.setbuilder.vibe_enrichment.Gateway.dispatch", new=AsyncMock(...))`; build `ChatResponse` fixtures with a `ToolCall(name="submit_track_vibes", input={...})`):
- `test_100_tracks_costs_5_calls` — seed 100 pool tracks (direct `SetPoolTrack` inserts with distinct `track_id`/`dedupe_sig`), mock returns full batch; assert `llm_calls == 5`, `enriched == 100`, dispatch call count == 5 **(acceptance criterion)**.
- `test_second_run_is_fully_cached` — run twice; second run: `llm_calls == 0`, `cached == 100` **(acceptance: second DJ pays zero — also assert a different actor/set with the same track keys gets `cached`)**.
- `test_prompt_version_bump_reenriches` — seed a `TrackVibe` row with `prompt_version="v0"`; assert the track is re-enriched.
- `test_malformed_items_skipped` — out-of-range index, energy 99 (clamped), bad transitional_role (nulled), confidence 1.7 (clamped); assert stored values.
- `test_llm_error_marks_remaining_failed` — first dispatch OK, second raises `ProviderUnavailable`; with 40 tracks assert `enriched == 20`, `failed == 20`, `llm_calls` counts only successful+attempted per implementation (assert == 2).
- `test_no_llm_configured_propagates` — dispatch raises `NoLlmConfigured`; `pytest.raises`.
- `test_track_without_track_id_uses_sig_key` — track with `track_id=None`; assert TrackVibe row keyed `sig:<dedupe_sig>`.

Steps: write tests → verify fail → implement module → pass → commit `feat(setbuilder): TrackVibe batch LLM enrichment via gateway`.

---

### Task 4: community_vibe aggregation service

**Files:**
- Create: `server/app/services/setbuilder/community_vibe.py`
- Test: `server/tests/test_setbuilder_vibes.py` (append)

Contract:

```python
@dataclass(frozen=True)
class CommunityVibe:
    energy: int | None
    mood: str | None
    sample_size: int

def community_consensus(
    db: Session, track_keys: Iterable[str], *, min_sample: int, max_stddev: float
) -> dict[str, CommunityVibe]
```

- Fetch all `TrackVibeOverride` rows for the keys ordered by id; keep the **latest row per (track_id, user_id)** as that user's vote.
- Energy: votes = non-null `energy_override`; consensus when `len(votes) >= min_sample and statistics.pstdev(votes) < max_stddev` → `round(statistics.fmean(votes))`.
- Mood: votes = non-null `mood_override`; `Counter.most_common(1)` wins when its count `>= min_sample` and `> len(votes)/2`.
- Include a key in the result only when at least one field reached consensus; `sample_size = max(len(energy_votes), len(mood_votes))`.

Tests (insert `TrackVibeOverride` rows directly; users via `User` model like `test_llm_gateway._make_connector` pattern):
- `test_consensus_requires_min_sample` — 2 votes, no consensus; 3 votes (energies 7,7,8) → energy 7.
- `test_consensus_rejected_on_high_stddev` — energies 1, 5, 10 (pstdev ≈ 3.68 ≥ 1.5) → no energy consensus.
- `test_latest_vote_per_user_wins` — same user votes 2 then 8; only the 8 counts.
- `test_mood_majority` — moods ["dark","dark","euphoric"] with min_sample=3 → "dark"; ["dark","euphoric","happy"] → None.
- `test_thresholds_are_tunable` — pass `min_sample=2` and assert 2 votes now reach consensus.

Steps: tests → fail → implement → pass → commit `feat(setbuilder): community vibe consensus aggregation`.

---

### Task 5: precedence resolver + read-time state builder

**Files:**
- Create: `server/app/services/setbuilder/vibe_resolver.py`
- Test: `server/tests/test_setbuilder_vibes.py` (append)

Contract:

```python
LOW_CONFIDENCE_THRESHOLD = 0.5

@dataclass(frozen=True)
class OwnVibe:
    energy: int | None
    mood: str | None

@dataclass(frozen=True)
class ResolvedVibe:
    energy: int | None
    energy_source: str | None  # "own" | "community" | "llm" | None
    mood: str | None
    mood_source: str | None

def resolve_vibe(
    own: OwnVibe | None, community: CommunityVibe | None, llm: TrackVibe | None
) -> ResolvedVibe

def is_low_confidence(vibe: TrackVibe) -> bool  # confidence is None or < 0.5

@dataclass(frozen=True)
class TrackVibeState:
    pool_track_id: int
    vibe_key: str
    own: OwnVibe | None
    community: CommunityVibe | None
    llm: TrackVibe | None
    resolved: ResolvedVibe

def build_pool_vibe_states(db: Session, actor: User, set_obj: Set) -> list[TrackVibeState]
```

- `resolve_vibe` cascades **per field** (own → community → llm); an own override with only energy set still lets mood fall through to community/llm.
- `build_pool_vibe_states`: loads pool tracks; own tier = latest `TrackVibeOverride` per track for `actor.id` (None when both override fields null); community tier from `community_consensus` using `get_system_settings(db)` thresholds; llm tier = newest matching-version `TrackVibe` row per key.

Tests — **acceptance criterion: resolver covered for all three tiers**:
- `test_own_override_wins` / `test_community_beats_llm` / `test_llm_fallback` / `test_no_tiers_resolves_none`
- `test_per_field_cascade` — own has energy only, community has mood only → energy_source "own", mood_source "community".
- `test_low_confidence_flag` — confidence 0.3 → True; 0.5 → False; None → True.
- `test_build_pool_vibe_states_end_to_end` — seed 1 pool track + own override + 3 community votes + TrackVibe row; assert all tiers populated and resolved follows precedence.

Steps: tests → fail → implement → pass → commit `feat(setbuilder): three-tier vibe precedence resolver`.

---

### Task 6: API endpoints + schemas

**Files:**
- Modify: `server/app/schemas/setbuilder.py` (new section)
- Modify: `server/app/api/setbuilder.py` (two endpoints + imports)
- Test: `server/tests/test_setbuilder_vibes_api.py` (new)

Schemas (append to `schemas/setbuilder.py`):

```python
# ---------------------------------------------------------------------------
# Track vibes (issue #391) — read-only three-tier display + enrichment trigger


class OwnVibeOut(BaseModel):
    energy: int | None
    mood: str | None


class CommunityVibeOut(BaseModel):
    energy: int | None
    mood: str | None
    sample_size: int


class LlmVibeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    energy: int | None
    mood: str | None
    era: str | None
    sing_along: bool | None
    dance_floor: bool | None
    transitional_role: str | None
    confidence: float | None
    low_confidence: bool
    llm_provider: str
    llm_model: str


class ResolvedVibeOut(BaseModel):
    energy: int | None
    energy_source: Literal["own", "community", "llm"] | None
    mood: str | None
    mood_source: Literal["own", "community", "llm"] | None


class TrackVibeStateOut(BaseModel):
    pool_track_id: int
    vibe_key: str
    own: OwnVibeOut | None
    community: CommunityVibeOut | None
    llm: LlmVibeOut | None
    resolved: ResolvedVibeOut


class PoolVibesState(BaseModel):
    tracks: list[TrackVibeStateOut]


class VibeEnrichmentResult(BaseModel):
    enriched: int
    cached: int
    failed: int
    llm_calls: int
    vibes: PoolVibesState
```

Endpoints (append to `api/setbuilder.py`; `LlmVibeOut` is built via a small helper that injects `low_confidence=is_low_confidence(row)`):

```python
@router.get("/sets/{set_id}/pool/vibes", response_model=PoolVibesState)
@limiter.limit("60/minute")
def get_pool_vibes(set_id, request, db=Depends(get_db), current_user=Depends(get_current_active_user)) -> PoolVibesState:
    """Three-tier vibe state (own / community / LLM) for the set's pool."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    return _pool_vibes_state(db, current_user, set_obj)


@router.post("/sets/{set_id}/pool/vibes/enrich", response_model=VibeEnrichmentResult)
@limiter.limit("5/minute")
async def enrich_pool_vibes(set_id, request, db=Depends(get_db), current_user=Depends(get_current_active_user)) -> VibeEnrichmentResult:
    """Batch-enrich uncached pool tracks via the LLM gateway (20 tracks/call)."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    try:
        stats = await vibe_enrichment.enrich_pool_vibes(db, current_user, set_obj)
    except NoLlmConfigured:
        raise HTTPException(
            status_code=400,
            detail="No AI connector configured — connect one in Settings → AI.",
        ) from None
    return VibeEnrichmentResult(
        enriched=stats.enriched, cached=stats.cached, failed=stats.failed,
        llm_calls=stats.llm_calls, vibes=_pool_vibes_state(db, current_user, set_obj),
    )
```

API tests (`test_setbuilder_vibes_api.py`, reuse `set_id`/`other_dj_headers` fixture patterns from `test_setbuilder_pool_api.py`):
- ownership 404s for both endpoints; 401 without auth.
- `GET .../vibes` empty pool → `{"tracks": []}`.
- enrich end-to-end with mocked `Gateway.dispatch` (patch at `app.services.setbuilder.vibe_enrichment.Gateway.dispatch`): seed 2 pool tracks via the manual-import endpoint, assert response counts + `vibes.tracks[*].llm` populated with provider/model + `low_confidence` flags.
- `NoLlmConfigured` → 400 with the friendly message.
- precedence visible over API: seed own override row → `resolved.energy_source == "own"`.

Steps: tests → fail → implement → pass → run full backend test suite (`pytest -q`) → commit `feat(setbuilder): pool vibes read + enrich endpoints`.

---

### Task 7: OpenAPI regen + frontend API client

**Files:**
- Regenerate: `server/openapi.json`, `dashboard/lib/api-types.generated.ts`
- Modify: `dashboard/lib/api-types.ts`, `dashboard/lib/api.ts`

- [ ] From `<worktree>/server`: `/home/adam/github/WrzDJ/server/.venv/bin/python scripts/export_openapi.py`
- [ ] From `<worktree>/dashboard`: `npx openapi-typescript ../server/openapi.json -o lib/api-types.generated.ts`
- [ ] `api-types.ts` — append aliases:

```typescript
export type PoolVibesState = Schemas['PoolVibesState'];
export type TrackVibeState = Schemas['TrackVibeStateOut'];
export type VibeEnrichmentResult = Schemas['VibeEnrichmentResult'];
```

- [ ] `api.ts` — next to `getPool`:

```typescript
  async getPoolVibes(setId: number): Promise<PoolVibesState> {
    return this.fetch(`/api/setbuilder/sets/${setId}/pool/vibes`);
  }
  async enrichPoolVibes(setId: number): Promise<VibeEnrichmentResult> {
    return this.fetch(`/api/setbuilder/sets/${setId}/pool/vibes/enrich`, { method: 'POST' });
  }
```

- [ ] Run `npx tsc --noEmit` from dashboard — PASS. Commit `feat(setbuilder): pool vibes API client + generated types`.

---

### Task 8: VibeTiers component + PoolPanel integration

**Files:**
- Create: `dashboard/app/(dj)/setbuilder/components/VibeTiers.tsx`
- Modify: `dashboard/app/(dj)/setbuilder/components/PoolPanel.tsx`
- Modify: `dashboard/app/(dj)/setbuilder/setbuilder.module.css`
- Test: `dashboard/app/(dj)/setbuilder/components/__tests__/VibeTiers.test.tsx`

`VibeTiers` (read-only, inline styles + a few module classes, dark theme): renders three side-by-side tier chips — `You`, `Crowd` (with sample size), `AI` — each showing `E{n}` energy + mood text, `—` when the tier is missing. AI chip with `low_confidence` gets warning styling (dashed amber border, `⚠` prefix, `title="Low confidence — review"`). Resolved field sources get a subtle highlight (the winning tier chip gets a brighter border).

PoolPanel additions (state + handlers, following existing patterns):
- `const [vibes, setVibes] = useState<Map<number, TrackVibeState>>(new Map());`
- `const [showVibes, setShowVibes] = useState(false);` + `vibesBusy` flag.
- Header gains a `Vibes` toggle button (fetches `api.getPoolVibes(setId)` on first enable) and, when `showVibes`, an `Analyze` button calling `api.enrichPoolVibes(setId)` → updates map → toast `` `${r.enriched} analyzed · ${r.cached} cached · ${r.failed} failed` `` (errors → toast with API detail when 400).
- Track rows render `<VibeTiers state={vibes.get(t.id)} />` under `trackMetaRow` when `showVibes`.

Vitest (`VibeTiers.test.tsx`, jsdom + testing-library, mirroring `PoolPanel.test.tsx` conventions): all three tiers rendered side-by-side; missing tiers show placeholders; low-confidence flag visible only when `llm.low_confidence`; sample size shown on community tier.

Steps: tests → fail → implement → `npm run lint && npx tsc --noEmit && npm test -- --run` → commit `feat(setbuilder): three-tier vibe display in pool panel`.

---

### Task 9: Full local CI + finish

- [ ] Backend (from `<worktree>/server`, main venv binaries): `ruff check .` · `ruff format --check .` · `bandit -r app -c pyproject.toml -q` · `pytest --tb=short -q` · `alembic upgrade head && alembic check`
- [ ] Frontend (from `<worktree>/dashboard`): `npm run lint` · `npx tsc --noEmit` · `npm test -- --run`
- [ ] `git checkout -- dashboard/next-env.d.ts` if modified
- [ ] superpowers:finishing-a-development-branch → option 2 (Push + PR). PR body: `Closes #391` + Design decisions section (items 1–9 above).
