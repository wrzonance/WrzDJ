# Fix: Tidal Bidirectional Removal Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure Tidal track removal on rejection only fires when the DJ has explicitly enabled bidirectional sync (`tidal_collection_bidirectional = True`), not just when `tidal_sync_enabled = True`.

**Architecture:** Two API paths both call Tidal removal but neither checks the `tidal_collection_bidirectional` flag — the background poller already does this correctly, so the fix aligns the two rejection paths with the poller's existing logic. No new abstractions needed; this is a two-line guard addition backed by two new regression tests and two updated existing tests.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, pytest

---

## Background

`tidal_collection_bidirectional` (defaults `False`) is the DJ's opt-in flag for bidirectional Tidal sync. Currently:

| Path | Checks `tidal_sync_enabled` | Checks `tidal_collection_bidirectional` |
|------|-----------------------------|-----------------------------------------|
| Single rejection `PATCH /api/requests/{id}` (`requests.py:82–86`) | ✅ | ❌ **missing** |
| Bulk review `POST /api/events/{code}/bulk-review` (`events.py:1125`) | ✅ | ❌ **missing** |
| Background poller `_run_tidal_collection_poll` (`main.py:47–48`) | ✅ | ✅ correct |

Because `tidal_collection_bidirectional` defaults to `False`, every DJ with Tidal sync enabled has tracks silently removed from their collection playlist on rejection — regardless of whether they opted into bidirectional behavior.

---

## Files

- **Modify:** `server/app/api/requests.py:82–86` — add bidirectional guard to single-rejection path
- **Modify:** `server/app/api/events.py:1125` — add bidirectional guard to bulk-review path
- **Modify:** `server/tests/test_requests.py` — add regression test + update existing happy-path test
- **Modify:** `server/tests/test_collect_dj.py` — add regression test + update existing happy-path test

---

## Task 1: Add regression test for single rejection path

The new test asserts that with `tidal_sync_enabled=True` but `tidal_collection_bidirectional=False` (the default), rejection does **not** queue Tidal removal. This test will **fail** before the fix is applied (proving the bug exists).

**Files:**
- Modify: `server/tests/test_requests.py` — insert after line 792 (end of `TestPatchRejectionTidalRemoval` class)

- [ ] **Step 1: Write the failing test**

Open `server/tests/test_requests.py`. Find the class `TestPatchRejectionTidalRemoval` and add this test method after the existing `test_rejecting_unsynced_collection_request_skips_tidal` method:

```python
def test_rejecting_synced_request_skips_tidal_when_bidirectional_disabled(
    self, client: TestClient, db: Session, auth_headers: dict, test_event: Event, monkeypatch
):
    """Rejection must NOT remove from Tidal when bidirectional sync is off (the default)."""
    from app.models.request import Request as SongRequest
    from app.models.request import RequestStatus

    test_event.tidal_sync_enabled = True
    test_event.tidal_collection_bidirectional = False  # explicit default
    db.commit()

    req = SongRequest(
        event_id=test_event.id,
        song_title="Guarded Track",
        artist="DJ Guard",
        status=RequestStatus.NEW.value,
        dedupe_key="guarded-track-dj-guard",
        submitted_during_collection=True,
        tidal_collection_track_id="tid-777",
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    calls = []

    def mock_remove(*args, **kwargs):
        calls.append(args)

    import app.api.requests as requests_module

    monkeypatch.setattr(requests_module, "remove_track_from_collection_playlist", mock_remove)

    resp = client.patch(
        f"/api/requests/{req.id}",
        json={"status": "rejected"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert len(calls) == 0, "Tidal removal must not fire when bidirectional sync is disabled"
```

- [ ] **Step 2: Run test to verify it fails (bug is confirmed)**

```bash
cd server && .venv/bin/pytest tests/test_requests.py::TestPatchRejectionTidalRemoval::test_rejecting_synced_request_skips_tidal_when_bidirectional_disabled -v
```

Expected: **FAIL** — `AssertionError: Tidal removal must not fire when bidirectional sync is disabled` (i.e., `len(calls)` is 1, not 0).

---

## Task 2: Add regression test for bulk-review path

Same logic: assert that bulk rejection with `tidal_sync_enabled=True` but `tidal_collection_bidirectional=False` does **not** queue batch removal.

**Files:**
- Modify: `server/tests/test_collect_dj.py` — insert after line 418 (after `test_bulk_reject_skips_tidal_removal_when_no_track_id`)

- [ ] **Step 1: Write the failing test**

Open `server/tests/test_collect_dj.py`. Add this function after `test_bulk_reject_skips_tidal_removal_when_no_track_id`:

```python
def test_bulk_reject_skips_tidal_removal_when_bidirectional_disabled(
    client, db, auth_headers, test_event, monkeypatch
):
    """Bulk rejection must NOT remove from Tidal when bidirectional sync is off (the default)."""
    from app.models.request import Request as SongRequest
    from app.models.request import RequestStatus

    req = SongRequest(
        event_id=test_event.id,
        song_title="Guarded Bulk Track",
        artist="DJ BulkGuard",
        status=RequestStatus.NEW.value,
        dedupe_key="guarded-bulk-track",
        submitted_during_collection=True,
        tidal_collection_track_id="tid-888",
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    test_event.tidal_sync_enabled = True
    test_event.tidal_collection_bidirectional = False  # explicit default
    db.commit()

    calls = []

    def fake_remove(db, user, event, track_ids):
        calls.append((db, user, event, track_ids))

    import app.api.events as events_module

    monkeypatch.setattr(events_module, "remove_collection_tracks_batch", fake_remove)

    resp = client.post(
        f"/api/events/{test_event.code}/bulk-review",
        json={"action": "reject_ids", "request_ids": [req.id]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert len(calls) == 0, "Tidal batch removal must not fire when bidirectional sync is disabled"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd server && .venv/bin/pytest tests/test_collect_dj.py::test_bulk_reject_skips_tidal_removal_when_bidirectional_disabled -v
```

Expected: **FAIL** — `AssertionError: Tidal batch removal must not fire when bidirectional sync is disabled`.

---

## Task 3: Apply the fix

Two-line change. Both rejection paths get the same `and event.tidal_collection_bidirectional` guard already present in the background poller.

**Files:**
- Modify: `server/app/api/requests.py:82–87`
- Modify: `server/app/api/events.py:1125`

- [ ] **Step 1: Fix the single-rejection path in `requests.py`**

Find this block (lines 82–87):

```python
    # Remove from Tidal collection playlist when a synced collection request is rejected
    if (
        update_data.status == RequestStatus.REJECTED
        and request.submitted_during_collection
        and request.tidal_collection_track_id
        and request.event.tidal_sync_enabled
    ):
```

Replace with:

```python
    # Remove from Tidal collection playlist when a synced collection request is rejected.
    # Requires bidirectional sync to be enabled — tidal_sync_enabled alone is not enough.
    if (
        update_data.status == RequestStatus.REJECTED
        and request.submitted_during_collection
        and request.tidal_collection_track_id
        and request.event.tidal_sync_enabled
        and request.event.tidal_collection_bidirectional
    ):
```

- [ ] **Step 2: Fix the bulk-review path in `events.py`**

Find this line (line 1125):

```python
    # Direction 1: remove rejected+synced tracks from the Tidal collection playlist
    if event.tidal_sync_enabled:
```

Replace with:

```python
    # Direction 1: remove rejected+synced tracks from the Tidal collection playlist.
    # Requires bidirectional sync to be enabled — tidal_sync_enabled alone is not enough.
    if event.tidal_sync_enabled and event.tidal_collection_bidirectional:
```

- [ ] **Step 3: Run the two new regression tests to verify they now pass**

```bash
cd server && .venv/bin/pytest tests/test_requests.py::TestPatchRejectionTidalRemoval::test_rejecting_synced_request_skips_tidal_when_bidirectional_disabled tests/test_collect_dj.py::test_bulk_reject_skips_tidal_removal_when_bidirectional_disabled -v
```

Expected: **PASS** for both.

---

## Task 4: Update happy-path tests to set `tidal_collection_bidirectional = True`

The existing happy-path tests (`test_rejecting_synced_collection_request_queues_tidal_removal` and `test_bulk_reject_queues_tidal_removal_for_synced_requests`) now fail because they set `tidal_sync_enabled = True` but not `tidal_collection_bidirectional = True`. Update them to reflect the new correct behavior.

**Files:**
- Modify: `server/tests/test_requests.py` — around line 721
- Modify: `server/tests/test_collect_dj.py` — around line 359

- [ ] **Step 1: Run the full test class to see which happy-path tests now fail**

```bash
cd server && .venv/bin/pytest tests/test_requests.py::TestPatchRejectionTidalRemoval -v
```

Expected: `test_rejecting_synced_collection_request_queues_tidal_removal` **FAIL** (calls is 0, expected 1).

- [ ] **Step 2: Update the single-rejection happy-path test**

In `server/tests/test_requests.py`, find `test_rejecting_synced_collection_request_queues_tidal_removal`. Locate these two lines:

```python
        test_event.tidal_sync_enabled = True
        db.commit()
```

Replace with:

```python
        test_event.tidal_sync_enabled = True
        test_event.tidal_collection_bidirectional = True
        db.commit()
```

- [ ] **Step 3: Update the bulk-review happy-path test**

In `server/tests/test_collect_dj.py`, find `test_bulk_reject_queues_tidal_removal_for_synced_requests`. Locate these two lines:

```python
    test_event.tidal_sync_enabled = True
    db.commit()
```

Replace with:

```python
    test_event.tidal_sync_enabled = True
    test_event.tidal_collection_bidirectional = True
    db.commit()
```

- [ ] **Step 4: Run all Tidal-related tests to confirm full suite green**

```bash
cd server && .venv/bin/pytest tests/test_requests.py::TestPatchRejectionTidalRemoval tests/test_collect_dj.py -v
```

Expected: All tests **PASS**.

---

## Task 5: Full CI check and commit

- [ ] **Step 1: Run the full backend test suite**

```bash
cd server && .venv/bin/pytest --tb=short -q
```

Expected: All tests pass, coverage ≥ 85%.

- [ ] **Step 2: Run linting**

```bash
cd server && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: No errors. If format errors, run `.venv/bin/ruff format .` then re-check.

- [ ] **Step 3: Run security scan**

```bash
cd server && .venv/bin/bandit -r app -c pyproject.toml -q
```

Expected: No issues.

- [ ] **Step 4: Commit**

```bash
git add server/app/api/requests.py server/app/api/events.py server/tests/test_requests.py server/tests/test_collect_dj.py
git commit -m "fix(security): guard Tidal collection removal behind bidirectional flag

Both rejection paths (single PATCH and bulk-review POST) were calling
remove_track_from_collection_playlist / remove_collection_tracks_batch
whenever tidal_sync_enabled was True, ignoring tidal_collection_bidirectional.
Since that flag defaults to False, every DJ with Tidal sync enabled had
tracks silently removed from their collection playlist on rejection.

Add the missing tidal_collection_bidirectional guard to both paths,
matching the logic already present in the background poller. Update
existing happy-path tests to set the flag; add regression tests for
the disabled-bidirectional case."
```
