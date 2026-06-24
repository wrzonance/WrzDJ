# Soundcharts "similar songs" candidate source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Soundcharts paid-tier "related tracks" (`GET /api/v2/song/{uuid}/related`) as a provider-agnostic recommendation candidate source seeded from the event's existing tracks (resolved by ISRC from the master `tracks` store), so a DJ with no connected Tidal/Beatport account still gets suggestions.

**Architecture:** A new dark-by-default adapter method `get_related_songs_by_isrc` on `services/soundcharts.py` resolves an ISRC → song UUID → related-tracks call. A new generator `related_candidates_from_seeds` in `recommendation/soundcharts_candidates.py` picks ISRC seeds from accepted/played requests (request.isrc first, then the master `tracks` store by signature), fetches related songs, dedups across seeds, and converts them to `TrackProfile(source="soundcharts")`. These candidates flow through the EXISTING `deduplicate_candidates` → `rank_candidates` → diversity/cap pipeline unchanged. `service.generate_recommendations` is extended to run this source even when no Tidal/Beatport is connected; the API gate is relaxed accordingly. The source surfaces as `"soundcharts"` in `services_used`.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, httpx, pytest. Ruff line-length 100.

## Global Constraints

- DARK BY DEFAULT, no spend by default: gate behind a new `soundcharts_related_tracks_enabled` setting (default `False`) AND configured creds. Absent → source contributes nothing, endpoint behaves exactly as today.
- NEVER log/print Soundcharts secrets (`SOUNDCHARTS_APP_ID`/`SOUNDCHARTS_API_KEY`). Read creds from settings only.
- Mock the Soundcharts adapter in tests; NEVER hit the live paid API.
- Parameterized queries only; validate external input; no internal errors/stack traces leaked to API.
- Do NOT modify `track_match.find_best_match`, `setbuilder/`, or `dashboard/`. Additive only — do not rework the #544 audio-features path.
- Coverage gate is enforced (`--cov-fail-under`). Keep it green with targeted tests.
- Conventional Commits; trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: Dark-by-default related-tracks adapter

**Files:**
- Modify: `server/app/core/config.py` (add `soundcharts_related_tracks_enabled: bool = False`)
- Modify: `server/app/services/soundcharts.py` (add `get_related_songs_by_isrc`)
- Test: `server/tests/test_soundcharts.py`

**Interfaces:**
- Produces: `get_related_songs_by_isrc(isrc: str, *, limit: int = 20) -> list[SoundchartsTrack]`
  - Returns `[]` when `soundcharts_related_tracks_enabled` is False, creds missing, ISRC unresolvable, or API failure.
  - Resolves ISRC → song object (`/api/v2.25/song/by-isrc/{isrc}`) → `GET /api/v2/song/{uuid}/related?offset=0&limit=N`.
  - Parses items tolerant of both `{"items":[{song obj}]}` and `{"items":[{"song":{...}}]}` shapes.

Steps: write failing tests (enabled+success returns tracks; disabled returns []; no creds returns []; bad ISRC returns []; HTTP error returns []; both response shapes parsed), run to fail, implement, run to pass, commit.

---

### Task 2: ISRC-seeded related-candidate generator

**Files:**
- Modify: `server/app/services/recommendation/soundcharts_candidates.py` (add `related_candidates_from_seeds`)
- Test: `server/tests/test_soundcharts_candidates.py`

**Interfaces:**
- Consumes: `get_related_songs_by_isrc` (Task 1); `TrackProfile`; `app.services.tracks.store.get_track`; `app.services.setbuilder.pool.dedupe_signature`.
- Produces: `related_candidates_from_seeds(db, requests, *, max_seeds=10, per_seed_limit=20) -> tuple[list[TrackProfile], int]`
  - For each seed request: ISRC = `request.isrc` or master-store lookup by `dedupe_signature(artist, title)`.
  - Skips seeds with no ISRC. Dedups related songs across seeds by `soundcharts_uuid` and by `artist|title`.
  - Returns `(candidates, seeds_used)` where candidates are `TrackProfile(source="soundcharts")` and `seeds_used` counts seeds that yielded an API call.

Steps: write failing tests (request.isrc seed → candidates; store-fallback seed; no-ISRC seed skipped; cross-seed dedup; empty requests → ([],0)), mock `get_related_songs_by_isrc`, run to fail, implement, run to pass, commit.

---

### Task 3: Wire source into the engine + relax the gate

**Files:**
- Modify: `server/app/services/recommendation/service.py` (`_search_candidates`, `generate_recommendations`)
- Modify: `server/app/api/events.py` (`get_recommendations` 503 gate)
- Test: `server/tests/test_recommendation_service.py`, `server/tests/test_recommendation_api.py`

**Interfaces:**
- Consumes: `related_candidates_from_seeds` (Task 2).
- `generate_recommendations` runs the related-tracks source when enabled, even with no Tidal/Beatport; adds `"soundcharts"` to `services_used`; junk-filters candidates with the existing helpers.
- API `get_recommendations` allows the request through (no 503) when `soundcharts_related_tracks_enabled` + creds are set, even with no connected service.

Steps: write failing tests (enabled + no connected service → non-empty suggestions + `"soundcharts"` in services_used; disabled → behaves as today / empty + 503 path unchanged), run to fail, implement, run to pass, commit.

---

### Task 4: Docs, CI gate, openapi regen

**Files:**
- Modify: `CLAUDE.md` env list (note the new flag) — optional, low-risk.
- Regenerate committed `openapi.json` only if the response schema changed (it does NOT — `services_used` is already a free-form list), so SKIP unless a diff appears.

Steps: run full backend CI gate locally (ruff check, ruff format --check, bandit, pytest+coverage). Fix. Commit any formatting. No migration (the new column-less boolean setting needs none).
