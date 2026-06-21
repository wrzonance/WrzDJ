# Background-Task Fresh-Session Normalization Implementation Plan

> **For agentic workers:** Implement task-by-task with TDD. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop FastAPI `BackgroundTasks` from pinning the request-scoped DB connection during slow external API calls by passing IDs (not request-scoped sessions or live ORM rows) and opening a fresh `SessionLocal()` inside each task.

**Architecture:** Every `background_tasks.add_task(...)` that today receives the request `db` or a live ORM row is rerouted through a small module-local fresh-session helper that takes IDs, opens its own `SessionLocal()`, re-queries, calls the real service function, and closes the session in a `finally`. This extends the pattern already established by `_enrich_with_fresh_session` / `_sync_requests_with_fresh_session` in `events.py`.

**Tech Stack:** FastAPI, SQLAlchemy, pytest (SQLite in-memory test DB).

## Global Constraints

- Backend coverage is an ENFORCED gate (`--cov-fail-under` in `server/pyproject.toml`). Do NOT lower it.
- ruff line-length 100; rules E, F, I, UP. Run `ruff format` after edits.
- No new abstraction beyond the existing fresh-session helper pattern (DRY without over-abstraction).
- Immutability / comprehensive error handling: each helper MUST close its session in `finally`.
- No migration expected; verify `alembic check` reports no drift.

---

### Task 1: `events.py` fresh-session helpers for collection sync + removal

**Files:**
- Modify: `server/app/api/events.py` (add 2 helpers near existing ones ~1282-1315; rewire call sites at 738, 1186, 1253-1259, 1262-1274)
- Test: `server/tests/test_bg_fresh_sessions.py` (new)

**Interfaces:**
- Produces:
  - `_sync_collection_requests_with_fresh_session(event_id: int, request_ids: list[int]) -> None`
  - `_remove_collection_tracks_with_fresh_session(event_id: int, track_ids: list[str]) -> None`
  - reuse existing `_enrich_with_fresh_session(request_id)` and `_sync_requests_with_fresh_session(request_ids)`.

- [ ] **Step 1:** Write failing tests asserting the new helpers close their session on success and on exception, and that endpoints schedule IDs (not ORM objects).
- [ ] **Step 2:** Run them — they fail (helpers missing / endpoints still pass ORM objects).
- [ ] **Step 3:** Add the 2 helpers; rewire `accept-all` (738), `sync-tidal` (1186/1192), `bulk_review` (1253-1259, 1262-1274) to pass IDs through the helpers.
- [ ] **Step 4:** Run tests — pass.
- [ ] **Step 5:** Commit.

### Task 2: `requests.py` fresh-session helpers

**Files:**
- Modify: `server/app/api/requests.py` (call sites 79, 90-96, 158)
- Test: `server/tests/test_bg_fresh_sessions.py`

**Interfaces:**
- Produces:
  - `_enrich_with_fresh_session(request_id: int) -> None`
  - `_sync_request_to_services_with_fresh_session(request_id: int) -> None`
  - `_remove_collection_track_with_fresh_session(request_id: int, track_id: str) -> None`

- [ ] TDD as Task 1, updating the existing `remove_track_from_collection_playlist` monkeypatch tests in `test_requests.py` to the new IDs-only signature.

### Task 3: `collect.py` fresh-session helpers

**Files:**
- Modify: `server/app/api/collect.py` (call sites 466, 468-470)
- Test: `server/tests/test_bg_fresh_sessions.py`

**Interfaces:**
- Produces:
  - `_enrich_with_fresh_session(request_id: int) -> None`
  - `_sync_collection_requests_with_fresh_session(event_id: int, request_ids: list[int]) -> None`

- [ ] TDD as Task 1.

### Task 4: Update existing tests that monkeypatch the now-rewired functions

**Files:**
- Modify: `server/tests/test_collect_dj.py` (bulk_reject tests at 340-462 — `remove_collection_tracks_batch` now wrapped by helper)

- [ ] Adjust monkeypatch targets / signatures so the existing behavioral assertions still hold against the IDs-only path.

### Task 5: Bulk-review regression — no N long-lived sessions

- [ ] Add a test: bulk-review accepting multiple rows schedules N enrich tasks each via the fresh-session helper (IDs only) + one sync task with a list of IDs; assert no ORM object / request-scoped session is captured.
