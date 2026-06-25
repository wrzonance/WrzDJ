# Pool import: background enrichment + progress

**Issue:** #563 · **Date:** 2026-06-24 · **Branch:** `feat/pool-import-background-enrichment`

## Problem

Importing a playlist into a set pool blocks for tens of seconds (~44s for a 48-track Tidal
playlist on a cold cache) and the UI appears frozen. Root cause: `pool.hydrate_candidates_from_store`
enriches **inline, sequentially, synchronously** — each gap track triggers `enrich_track()` (up to two
serial external searches: Beatport + Tidal). Not rate-limiting (no 429s; Soundcharts dark). The backend
stays responsive (threadpool `def` route); the freeze is the **frontend awaiting the long fetch with no
progress feedback**. Cache-aside (#541/#542) makes this worst-case first-touch only.

## Goals
- Import request returns fast (~1–2s) regardless of how many tracks need enrichment.
- Gap tracks enrich in the background; the user sees tracks immediately and a progress bar to 100%.
- Reuse the existing background pattern; respect provider rate limits; no correctness regressions.

## Non-goals
- Durable task queue (celery/arq) — out of scope; `BackgroundTasks` + fresh session matches current infra.
- Soundcharts enablement (#544/#556 flags) and any change to the enrichment *cascade* itself.

## Design

### Backend

**1. Import returns fast (the four import endpoints: tidal/beatport/event/url).**
Split `hydrate_candidates_from_store` so the synchronous request path only does the **cheap** half:
create pool rows from the raw candidates and hydrate tracks **already present** in the master `tracks`
store (no external calls). Tracks with a store gap are inserted unenriched and marked `pending`. The
endpoint returns `PoolImportResult` immediately and enqueues the background job.

**2. Background enrich job (mirrors `collect.py` `_enrich_with_fresh_session`).**
`background_tasks.add_task(enrich_pool_tracks, set_id, gap_track_ids)`. The job:
- opens a **fresh `SessionLocal()`** (never the request session — #505),
- enriches the gap tracks with **bounded concurrency** via `ThreadPoolExecutor(max_workers=POOL_ENRICH_CONCURRENCY)` (default 6; `enrich_track` is sync httpx, so threads are correct),
- writes results through to the master store (existing `_enrich_and_writeback`) and updates the pool row,
- sets each pool track's `enrichment_status` to `enriched` (or `failed` on per-track error — isolated + logged), committing per track so progress is observable as it runs.

**3. Data model.** Add `SetPoolTrack.enrichment_status: Mapped[str]` — `"pending" | "enriched" | "failed"`,
default `"pending"`, `server_default="pending"`. One Alembic migration. Tracks hydrated from the store at
import time are written directly as `"enriched"`.

**4. Progress surfacing.** `PoolState` gains a set-level summary
`enrichment: { total, enriched, failed, pending, in_progress: bool }` derived from the set's pool-track
statuses (the progress bar reads this). `PoolTrackOut` also gains `enrichment_status` so the UI *may* show a
per-row pending/failed badge (optional, cheap). No new endpoint — the existing `GET /sets/{id}/pool` carries both.

### Frontend
- After import, the modal closes and tracks render immediately (they already come back in `PoolImportResult` / the pool refetch).
- While `enrichment.in_progress` (pending > 0), the pool panel shows a **progress bar + "Enriching N/total…"**, polling `GET /sets/{id}/pool` every ~2.5s (stop when `pending == 0`).
- Vanilla CSS / inline styles, dark theme (project rule). Reuse existing bar styling if present.

## Data flow
`import endpoint` → create rows + hydrate cache-hits (sync, fast) → return + `add_task` →
`enrich_pool_tracks(fresh session, bounded pool)` → per track: `enrich_track` → store write-back → set status →
frontend polls pool-state → bar fills → 100% when `pending == 0`.

## Error handling
- Per-track enrichment failure → `enrichment_status = "failed"`, logged, **counts as done** for progress so the bar always completes; surfaced as "no data" in the UI.
- Background job must not touch the request's (closed) session — always a fresh `SessionLocal()`, closed in a `finally`.
- Re-import / recompute mid-enrichment is safe: recompute tolerates partial data (#543 None-degrades-neutrally).

## Testing
- **Unit:** import endpoint returns without making external enrichment calls (mock `enrich_track`, assert not called inline); background `enrich_pool_tracks` uses a fresh session, enriches gaps, sets statuses, isolates a failing track (one `failed`, others `enriched`); concurrency bound respected.
- **Schema/migration:** `alembic upgrade head && alembic check` clean; default `pending`.
- **Progress:** pool-state returns correct enriched/total/pending counts across states.
- **Frontend (vitest):** progress component renders bar from counts; polling starts when pending>0 and stops at 0; tracks render pre-enrichment.
- Backend coverage ≥ enforced gate.

## Rollout
Single PR into `main`. Backward compatible. The migration **backfills terminal statuses only** — there is
no background worker at migration time, so no legacy row may be left `pending` (it would report
`in_progress` forever with nothing to clear it). Rows whose full contract is present (bpm, key, genre, and
duration_sec — mirroring `_has_provider_gap`) become `enriched`; partial/empty rows become `failed`, which
is exactly what the runtime worker now records when a pass can't close the gap. Legacy `failed` rows
re-enrich on their next import/recompute touch.
