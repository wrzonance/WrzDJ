# Dual-Code Routing Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the live `/join` page work end-to-end via the real `join_code` share link by resolving every guest-facing endpoint through one canonical lookup that accepts either of an event's two public codes, and stop leaking the private `event.id` to guests.

**Architecture:** One new resolver `get_event_by_public_code_with_status` = `or_(Event.code, Event.join_code)` replaces the per-router lookups on the guest surface (collect router, events search/submit, public reads, SSE stream). A new guest-safe `GET /api/public/events/{code}` returns a projection with no `event.id`. The behavioral boundary (frictionless vs collect-auth) stays enforced by flags/auth deps, never by code identity. SSE submit publishes the resolved `event.code` so a join_code submit reaches the stream. Frontend swaps the id-leaking `getEvent` for `getPublicEvent`; `NicknameGate` is untouched. No DB migration.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (backend), pytest; Next.js 16 / React 19 + TypeScript (frontend), vitest; OpenAPI-typescript codegen.

**Spec:** `docs/superpowers/specs/2026-05-30-dual-code-routing-design.md`

---

## File Structure

**Backend (create):**
- `server/tests/test_dual_code_routing.py` — resolver unit tests, events submit-by-join_code, get_event-stays-collection-only, SSE channel-match, new endpoint (no-id-leak + fields).

**Backend (modify):**
- `server/app/services/event.py` — add `get_event_by_public_code_with_status`.
- `server/app/api/collect.py` — `_get_event_or_404` → canonical resolver.
- `server/app/api/events.py` — `event_search` + `submit_request` → canonical; `submit_request` publishes `event.code`.
- `server/app/api/public.py` — `get_public_requests` / `check_has_requested` / `get_my_requests` → canonical; add `PublicEventResponse` schema + `GET /events/{code}` endpoint.
- `server/app/api/sse.py` — `event_stream` → canonical (still subscribes `event.code`).
- `server/tests/test_collect_public.py` — add join_code-resolution + frictionless-flag-boundary tests (reuses its autouse human-cookie fixture).

**Frontend (modify):**
- `server/openapi.json` + `dashboard/lib/api-types.generated.ts` — regenerated.
- `dashboard/lib/api-types.ts` — add `PublicEvent` alias.
- `dashboard/lib/api.ts` — add `getPublicEvent`; export `PublicEvent`.
- `dashboard/app/join/[code]/page.tsx` — `getEvent`→`getPublicEvent`; drop `getCollectEvent`; phase-banner link uses `collection_code`; `event` state typed `PublicEvent`.
- `dashboard/app/join/[code]/__tests__/page.test.tsx` — update mocks.

---

## Task 0: Worktree environment + clean baseline

**Files:** none (setup only)

- [ ] **Step 1: Create the backend venv and install deps**

```bash
cd server
python3 -m venv .venv
.venv/bin/pip install -U pip wheel
.venv/bin/pip install -e ".[dev]" || .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
```
(Use whichever install path the repo provides — check `server/pyproject.toml` for the `[project.optional-dependencies] dev` group first.)

- [ ] **Step 2: Install frontend deps**

```bash
cd ../dashboard && npm install
```

- [ ] **Step 3: Verify clean backend baseline**

Run: `cd ../server && .venv/bin/pytest -q`
Expected: PASS (note the count; this is the green baseline).

- [ ] **Step 4: Verify clean frontend baseline**

Run: `cd ../dashboard && npm test -- --run`
Expected: PASS.

**If either baseline fails:** stop and report — do not start implementing on a red baseline.

---

## Task 1: Canonical guest resolver

**Files:**
- Modify: `server/app/services/event.py` (after `get_event_by_join_code_with_status`, ~line 130)
- Test: `server/tests/test_dual_code_routing.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_dual_code_routing.py
"""Issue #382 — guest endpoints resolve by EITHER public code (collection or join)."""

from app.models.event import Event
from app.services.event import (
    EventLookupResult,
    get_event_by_public_code_with_status,
)


def test_public_code_resolver_accepts_both_codes(db, test_event: Event):
    by_collection, s1 = get_event_by_public_code_with_status(db, test_event.code)
    by_join, s2 = get_event_by_public_code_with_status(db, test_event.join_code)
    assert by_collection is not None and by_join is not None
    assert by_collection.id == test_event.id == by_join.id
    assert s1 == EventLookupResult.FOUND
    assert s2 == EventLookupResult.FOUND


def test_public_code_resolver_is_case_insensitive(db, test_event: Event):
    ev, _ = get_event_by_public_code_with_status(db, test_event.join_code.lower())
    assert ev is not None and ev.id == test_event.id


def test_public_code_resolver_not_found(db):
    ev, status = get_event_by_public_code_with_status(db, "ZZZZZZ")
    assert ev is None
    assert status == EventLookupResult.NOT_FOUND
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_dual_code_routing.py -q`
Expected: FAIL — `ImportError: cannot import name 'get_event_by_public_code_with_status'`.

- [ ] **Step 3: Implement the resolver**

```python
# server/app/services/event.py — add after get_event_by_join_code_with_status (~line 130)

def get_event_by_public_code_with_status(
    db: Session, code: str
) -> tuple[Event | None, EventLookupResult]:
    """Resolve a guest-facing public code that may be EITHER the collection
    `code` or the live `join_code` (one event, two public handles). Behavioral
    gating (frictionless vs collect-auth) is enforced by each endpoint's
    flags/auth dependencies, never by which code resolved the event. Codes are
    globally unique across both columns (`generate_unique_event_code`), so this
    is collision-free.
    """
    event = (
        db.query(Event)
        .filter(or_(Event.code == code.upper(), Event.join_code == code.upper()))
        .first()
    )
    return _event_with_status(event)
```
(`or_` is already imported in this module.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_dual_code_routing.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add server/app/services/event.py server/tests/test_dual_code_routing.py
git commit -m "feat(routing): canonical guest resolver accepting either public code (#382)"
```

---

## Task 2: Collect router resolves by either code + flag-boundary holds

**Files:**
- Modify: `server/app/api/collect.py:65-69` (`_get_event_or_404`)
- Test: `server/tests/test_collect_public.py` (append; reuses its autouse `_default_guest_cookie` fixture)

- [ ] **Step 1: Write the failing tests**

```python
# server/tests/test_collect_public.py — append at end of file

def test_collect_preview_resolves_by_join_code(client, db, test_event: Event):
    """#382: the join page hits collect endpoints with join_code — must resolve."""
    _enable_collection(db, test_event)
    r = client.get(f"/api/public/collect/{test_event.join_code}")
    assert r.status_code == 200
    # The canonical collection code is echoed back, regardless of which code resolved it.
    assert r.json()["code"] == test_event.code


def test_join_config_resolves_by_join_code(client, db, test_event: Event):
    r = client.get(f"/api/public/collect/{test_event.join_code}/join-config")
    assert r.status_code == 200
    assert r.json() == {"frictionless_join": False}


def test_ensure_name_resolves_by_join_code_when_frictionless(client, db, test_event: Event):
    test_event.frictionless_join = True
    db.commit()
    r = client.post(
        f"/api/public/collect/{test_event.join_code}/guest/ensure-name", json={}
    )
    assert r.status_code == 200
    assert r.json()["auto_generated"] is True


def test_ensure_name_boundary_is_flag_not_code(client, db, test_event: Event):
    """The frictionless boundary is the flag, never the code: a non-frictionless
    event reached by join_code still refuses auto-naming."""
    # test_event.frictionless_join defaults to False
    r = client.post(
        f"/api/public/collect/{test_event.join_code}/guest/ensure-name", json={}
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "frictionless_disabled"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_collect_public.py -q -k "join_code or boundary"`
Expected: FAIL — preview/join-config/ensure-name return 404 for `join_code` (collection-only resolver).

- [ ] **Step 3: Implement — switch `_get_event_or_404` to the canonical resolver**

```python
# server/app/api/collect.py — replace _get_event_or_404 (lines 65-69)

def _get_event_or_404(db: Session, code: str) -> Event:
    # Resolve by EITHER public code (collection or join). Collect's gates
    # (require_verified_human / require_email_verified) still enforce auth, so
    # accepting a join_code here changes resolution, not authorization. Preserve
    # collect's existing "inactive -> 404" semantics.
    event, _ = get_event_by_public_code_with_status(db, code)
    if event is None or not event.is_active:
        raise HTTPException(status_code=404, detail="Event not found")
    return event
```
Add the import at the top of `collect.py` (extend the existing `from app.services... import` for event helpers, or add):
```python
from app.services.event import get_event_by_public_code_with_status
```

- [ ] **Step 4: Run to verify pass (and no collect regressions)**

Run: `.venv/bin/pytest tests/test_collect_public.py tests/test_collect_service.py -q`
Expected: PASS (new tests pass; all pre-existing collect tests still green — collection code still resolves identically).

- [ ] **Step 5: Commit**

```bash
git add server/app/api/collect.py server/tests/test_collect_public.py
git commit -m "fix(routing): collect router resolves by either public code (#382)"
```

---

## Task 3: events.py search + submit resolve by either code; SSE submit publishes event.code

**Files:**
- Modify: `server/app/api/events.py` — `event_search` (~line 398), `submit_request` (~line 623 + `publish_event` at ~660)
- Test: `server/tests/test_dual_code_routing.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
# server/tests/test_dual_code_routing.py — append

from app.services.event_bus import get_event_bus


def test_submit_request_resolves_by_join_code(client, db, test_event: Event):
    r = client.post(
        f"/api/events/{test_event.join_code}/requests",
        json={"artist": "Daft Punk", "title": "One More Time"},
    )
    assert r.status_code == 200


def test_get_event_stays_collection_only(client, db, test_event: Event):
    """The DJ/general GET /api/events/{code} is NOT made canonical — it stays
    collection-only and keeps leaking EventOut.id to the authed DJ. A guest
    join_code must NOT resolve here (guests use GET /api/public/events/{code})."""
    assert client.get(f"/api/events/{test_event.code}").status_code == 200
    assert client.get(f"/api/events/{test_event.join_code}").status_code == 404


def test_submit_via_join_code_publishes_on_event_code_channel(client, db, test_event: Event):
    """SSE channels are keyed by event.code; the stream subscribes by event.code
    after resolving join_code. So a join_code submit must publish on event.code,
    else the guest's own submit never reaches the guest's own stream."""
    bus = get_event_bus()
    queue = bus.subscribe(test_event.code)  # mirrors sse.py: subscribes event.code
    try:
        r = client.post(
            f"/api/events/{test_event.join_code}/requests",
            json={"artist": "Stardust", "title": "Music Sounds Better"},
        )
        assert r.status_code == 200
        msg = queue.get_nowait()  # raises if nothing published to event.code
        assert msg["event"] == "request_created"
    finally:
        bus.unsubscribe(test_event.code, queue)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_dual_code_routing.py -q -k "submit or get_event_stays"`
Expected: FAIL — `submit_request` 404s on `join_code`; the SSE test's `get_nowait()` raises `QueueEmpty` (publishes on the URL join_code channel, not event.code).

- [ ] **Step 3: Implement**

In `event_search` (~line 398) replace:
```python
    event_obj, lookup_result = get_event_by_code_with_status(db, code)
```
with:
```python
    event_obj, lookup_result = get_event_by_public_code_with_status(db, code)
```

In `submit_request` (~line 623) replace:
```python
    event, lookup_result = get_event_by_code_with_status(db, code)
```
with:
```python
    event, lookup_result = get_event_by_public_code_with_status(db, code)
```

In `submit_request`'s SSE publish (~line 660) replace `code` with `event.code`:
```python
    if not is_duplicate:
        publish_event(
            event.code,  # canonical SSE channel key (matches the stream subscriber)
            "request_created",
            {
                "request_id": song_request.id,
                "title": song_request.song_title,
                "artist": song_request.artist,
            },
        )
```

Add to the events.py import of event services:
```python
from app.services.event import get_event_by_public_code_with_status
```
(keep `get_event_by_code_with_status` imported — `get_event` still uses it.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_dual_code_routing.py tests/test_events.py -q`
Expected: PASS (new tests pass; existing events tests still green — collection code still resolves for submit/search).

- [ ] **Step 5: Commit**

```bash
git add server/app/api/events.py server/tests/test_dual_code_routing.py
git commit -m "fix(routing): events search/submit resolve by either code; SSE publishes event.code (#382)"
```

---

## Task 4: public.py guest reads + SSE stream resolve by either code

**Files:**
- Modify: `server/app/api/public.py` — `get_public_requests` (~191), `check_has_requested` (~258), `get_my_requests` (~291); import line 18.
- Modify: `server/app/api/sse.py` — `event_stream` (~80).
- Test: `server/tests/test_dual_code_routing.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_dual_code_routing.py — append

def test_public_requests_resolve_by_either_code(client, db, test_event: Event):
    # Already worked by join_code; now also resolves by collection code (one resolver).
    assert client.get(f"/api/public/events/{test_event.join_code}/requests").status_code == 200
    assert client.get(f"/api/public/events/{test_event.code}/requests").status_code == 200
    assert client.get(f"/api/public/events/{test_event.join_code}/has-requested").status_code == 200
    assert client.get(f"/api/public/events/{test_event.code}/has-requested").status_code == 200
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_dual_code_routing.py -q -k "either_code"`
Expected: FAIL — the `code` (collection) variants 404 (public reads are join_code-only today).

- [ ] **Step 3: Implement**

In `public.py` line 18 change the import:
```python
from app.services.event import (
    EventLookupResult,
    get_event_by_join_code_with_status,        # still used by get_kiosk_display
    get_event_by_public_code_with_status,
)
```
In `get_public_requests`, `check_has_requested`, `get_my_requests`, replace each:
```python
    event, lookup_result = get_event_by_join_code_with_status(db, code)
```
with:
```python
    event, lookup_result = get_event_by_public_code_with_status(db, code)
```
(Leave `get_kiosk_display` on `get_event_by_join_code_with_status` — kiosk is a separate surface, out of scope.)

In `sse.py` `event_stream` (~80) replace:
```python
    event, result = get_event_by_join_code_with_status(db, code)
```
with:
```python
    event, result = get_event_by_public_code_with_status(db, code)
```
and update the `sse.py` import line accordingly (add `get_event_by_public_code_with_status`). The generator still subscribes `event.code` — unchanged.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_dual_code_routing.py tests/test_public.py tests/test_sse_security.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/app/api/public.py server/app/api/sse.py server/tests/test_dual_code_routing.py
git commit -m "fix(routing): public guest reads + SSE stream resolve by either code (#382)"
```

---

## Task 5: New guest-safe `GET /api/public/events/{code}` (no event.id)

**Files:**
- Modify: `server/app/api/public.py` — add `PublicEventResponse` schema (near the other schemas, ~line 75) + endpoint (after `get_kiosk_display`).
- Test: `server/tests/test_dual_code_routing.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
# server/tests/test_dual_code_routing.py — append

def test_public_event_endpoint_resolves_both_and_omits_id(client, db, test_event: Event):
    for code in (test_event.join_code, test_event.code):
        r = client.get(f"/api/public/events/{code}")
        assert r.status_code == 200, code
        body = r.json()
        # Serializer hygiene: the private surrogate key must never be emitted.
        assert "id" not in body
        assert test_event.id not in body.values()
        assert body["name"] == test_event.name
        assert body["collection_code"] == test_event.code
        assert body["frictionless_join"] is False
        assert body["requests_open"] is True
        assert body["phase"] in {"pre_announce", "collection", "live", "closed"}


def test_public_event_endpoint_404_and_410(client, db, test_event: Event):
    assert client.get("/api/public/events/ZZZZZZ").status_code == 404
    test_event.is_active = False
    db.commit()
    assert client.get(f"/api/public/events/{test_event.join_code}").status_code == 410
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_dual_code_routing.py -q -k "public_event_endpoint"`
Expected: FAIL — 404 (endpoint does not exist yet).

- [ ] **Step 3: Implement the schema + endpoint**

```python
# server/app/api/public.py — add near the schema block (after HasRequestedResponse, ~line 77)

class PublicEventResponse(BaseModel):
    """Guest-safe live-event projection. Deliberately omits event.id and any
    DJ-only fields (see #382 serializer hygiene)."""

    name: str
    collection_code: str
    requests_open: bool
    frictionless_join: bool
    phase: Literal["pre_announce", "collection", "live", "closed"]
    submission_cap_per_guest: int
    banner_url: str | None = None
    banner_colors: list[str] | None = None
```

```python
# server/app/api/public.py — add after get_kiosk_display

@router.get("/events/{code}", response_model=PublicEventResponse)
@limiter.limit("120/minute")
def get_public_event(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
) -> PublicEventResponse:
    """Guest-safe event info for the live /join page. Resolves by EITHER public
    code; never emits event.id. Replaces the join page's use of the DJ
    EventOut endpoint (which leaks the private id) and folds in phase +
    frictionless_join."""
    event, lookup_result = get_event_by_public_code_with_status(db, code)
    if lookup_result == EventLookupResult.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Event not found")
    if lookup_result == EventLookupResult.EXPIRED:
        raise HTTPException(status_code=410, detail="Event has expired")
    if lookup_result == EventLookupResult.ARCHIVED:
        raise HTTPException(status_code=410, detail="Event has been archived")

    banner_url = None
    banner_colors = None
    if event.banner_filename:
        api_base = str(request.base_url).rstrip("/")
        if request.headers.get("x-forwarded-proto") == "https" and api_base.startswith("http://"):
            api_base = "https://" + api_base[len("http://") :]
        banner_url = f"{api_base}/uploads/{event.banner_filename}"
        if event.banner_colors:
            banner_colors = json.loads(event.banner_colors)

    return PublicEventResponse(
        name=event.name,
        collection_code=event.code,
        requests_open=event.requests_open,
        frictionless_join=event.frictionless_join,
        phase=event.phase,
        submission_cap_per_guest=event.submission_cap_per_guest,
        banner_url=banner_url,
        banner_colors=banner_colors,
    )
```
(`json` and `Literal` are already imported in `public.py`.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_dual_code_routing.py -q`
Expected: PASS (all dual-code tests green).

- [ ] **Step 5: Commit**

```bash
git add server/app/api/public.py server/tests/test_dual_code_routing.py
git commit -m "feat(routing): guest-safe GET /api/public/events/{code} (no id leak) (#382)"
```

---

## Task 6: Regenerate OpenAPI types + frontend API client

**Files:**
- Regenerate: `server/openapi.json`, `dashboard/lib/api-types.generated.ts`
- Modify: `dashboard/lib/api-types.ts`, `dashboard/lib/api.ts`

- [ ] **Step 1: Regenerate the OpenAPI spec + TS types**

```bash
cd dashboard
npm run types:export     # server/.venv python writes server/openapi.json
npm run types:generate   # openapi-typescript -> lib/api-types.generated.ts
```
Expected: `PublicEventResponse` now present in `lib/api-types.generated.ts` (grep to confirm: `grep PublicEventResponse lib/api-types.generated.ts`).

- [ ] **Step 2: Add the `PublicEvent` alias**

```typescript
// dashboard/lib/api-types.ts — add near `export type Event = Schemas['EventOut'];`
export type PublicEvent = Schemas['PublicEventResponse'];
```

- [ ] **Step 3: Export `PublicEvent` + add the client method**

In `dashboard/lib/api.ts`, add `PublicEvent` to BOTH the `import type { … } from './api-types'` block (line 1) and the `export type { … } from './api-types'` block (line 44).

Add the method next to `getPublicRequests` (~line 743):
```typescript
  async getPublicEvent(code: string): Promise<PublicEvent> {
    return this.publicFetch(`${getApiUrl()}/api/public/events/${code}`);
  }
```

- [ ] **Step 4: Typecheck**

Run: `cd dashboard && npx tsc --noEmit`
Expected: PASS (no type errors; `PublicEvent` resolves).

- [ ] **Step 5: Commit**

```bash
git add server/openapi.json dashboard/lib/api-types.generated.ts dashboard/lib/api-types.ts dashboard/lib/api.ts
git commit -m "feat(api): getPublicEvent client + regenerated OpenAPI types (#382)"
```

---

## Task 7: Rewire the live `/join` page onto the guest-safe surface

**Files:**
- Modify: `dashboard/app/join/[code]/page.tsx`
- Test: `dashboard/app/join/[code]/__tests__/page.test.tsx`

> **Scope note (low-risk minimal change):** keep `getJoinConfig` for the pre-gate frictionless decision (it now resolves via the canonical resolver, so it works on `join_code`); swap only the id-leaking `getEvent` → `getPublicEvent` and drop `getCollectEvent` (phase now comes from `getPublicEvent`). Folding `getJoinConfig` into `getPublicEvent` is a deferred optional optimization — not done here to avoid disturbing the delicate gate choreography.

- [ ] **Step 1: Update the test mocks (failing first)**

In `dashboard/app/join/[code]/__tests__/page.test.tsx`:
- Add `getPublicEvent: vi.fn()` to the `mockApi` object (in the `vi.hoisted` block).
- In `setupDefaultMocks()`, add:
```typescript
  mockApi.getPublicEvent.mockResolvedValue({
    name: 'Test Event',
    collection_code: 'TEST01',
    requests_open: true,
    frictionless_join: false,
    phase: 'live',
    submission_cap_per_guest: 5,
    banner_url: null,
    banner_colors: null,
  });
```
- Add an assertion test:
```typescript
  it('loads the event via getPublicEvent and never calls the id-leaking getEvent', async () => {
    setupDefaultMocks();
    render(<JoinEventPage />);
    await waitFor(() => expect(mockApi.getPublicEvent).toHaveBeenCalledWith('TEST01'));
    expect(mockApi.getEvent).not.toHaveBeenCalled();
  });
```

- [ ] **Step 2: Run to verify failure**

Run: `cd dashboard && npm test -- --run app/join`
Expected: FAIL — page still calls `getEvent`; `getPublicEvent` never called.

- [ ] **Step 3: Implement the page changes**

In `dashboard/app/join/[code]/page.tsx`:

(a) Change the `event` state type import + declaration — replace `Event` with `PublicEvent`:
```typescript
import { api, ApiError, PublicEvent, GuestNowPlaying, GuestRequestInfo, SearchResult } from '@/lib/api';
```
```typescript
  const [event, setEvent] = useState<PublicEvent | null>(null);
```

(b) In `loadEvent` (~165), swap the loader and set phase here:
```typescript
  const loadEvent = useCallback(async () => {
    try {
      const data = await api.getPublicEvent(code);
      setEvent(data);
      setCollectPhase(data.phase);
      setError(null);
      try {
        const { has_requested } = await api.checkHasRequested(code);
        if (!has_requested) setShowRequestSheet(true);
      } catch {
        setShowRequestSheet(true);
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setError({ message: err.message, status: err.status });
      } else {
        setError({ message: 'Event not found or has expired.', status: 0 });
      }
    } finally {
      setLoading(false);
    }
  }, [code]);
```

(c) In the collect-phase effect (~193), drop `getCollectEvent` (phase now set in `loadEvent`); keep only the profile read for `email_verified`:
```typescript
  useEffect(() => {
    if (!gateComplete || !code) return;
    let cancelled = false;
    api.getCollectProfile(code)
      .then((profile) => {
        if (!cancelled) setEmailVerified(profile.email_verified);
      })
      .catch(() => { /* email-verified is best-effort on the live page */ });
    return () => { cancelled = true; };
  }, [code, gateComplete]);
```

(d) Phase-banner link (~507) — use the collection code from the resolved event, not the URL `join_code`:
```typescript
        🎟️ Pre-event voting is open —{' '}
        <a href={`/collect/${event.collection_code}`}>go to the pre-event page →</a>
```
(`event` is in scope here — this block renders after the `error || !event` guard.)

- [ ] **Step 4: Run to verify pass**

Run: `cd dashboard && npm test -- --run app/join && npx tsc --noEmit`
Expected: PASS (join tests green, including the new assertion; typecheck clean).

- [ ] **Step 5: Commit**

```bash
git add dashboard/app/join
git commit -m "fix(join): live page uses guest-safe getPublicEvent; collect link uses collection_code (#382)"
```

---

## Task 8: Full local CI gate

**Files:** none (validation; commit any fixes)

- [ ] **Step 1: Backend CI**

```bash
cd server
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/bandit -r app -c pyproject.toml -q
.venv/bin/pytest --tb=short -q
```
Expected: all pass; coverage ≥ threshold. Fix lint/format with `.venv/bin/ruff check --fix . && .venv/bin/ruff format .` and re-run.

- [ ] **Step 2: Alembic drift check (no migration expected)**

```bash
.venv/bin/alembic upgrade head && .venv/bin/alembic check
```
Expected: "No new upgrade operations detected." (no model change in this fix).

- [ ] **Step 3: Frontend CI**

```bash
cd ../dashboard
npm run lint
npx tsc --noEmit
npm test -- --run
git checkout next-env.d.ts 2>/dev/null || true   # auto-modified by builds; never commit
```
Expected: all pass.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A && git commit -m "chore: satisfy local CI for dual-code routing fix (#382)" || echo "nothing to fix"
```

- [ ] **Step 5: Push + open PR**

```bash
git push -u origin fix/dual-code-routing-382
gh pr create --base main --title "fix(routing): dual-code routing for frictionless /join (#382)" \
  --body "Closes #382. Canonical guest resolver (either public code) + guest-safe /api/public/events/{code} (no id leak) + SSE event.code publish. No migration. See docs/superpowers/specs/2026-05-30-dual-code-routing-design.md."
```

---

## Self-Review

**Spec coverage:**
- Canonical resolver → Task 1. ✓
- Collect router canonical → Task 2. ✓
- events search/submit canonical + SSE publish event.code → Task 3. ✓
- public reads + SSE stream canonical → Task 4. ✓
- New guest-safe endpoint (no id) → Task 5. ✓
- OpenAPI regen + client → Task 6. ✓
- Frontend rewire (getPublicEvent, drop getCollectEvent, collection_code link) → Task 7. ✓
- Drift guards: resolver-accepts-both (Task 1), serializer-hygiene no-id (Task 5), frictionless-flag-boundary (Task 2), SSE channel-match (Task 3). ✓
- `get_event` stays collection-only / DJ id-leak out of scope → pinned by `test_get_event_stays_collection_only` (Task 3). ✓
- No migration; CI gate → Task 8. ✓

**Placeholder scan:** none — every step has runnable code/commands.

**Type consistency:** backend `get_event_by_public_code_with_status` (Tasks 1–5) used identically everywhere; `PublicEventResponse` (backend) ↔ `Schemas['PublicEventResponse']` ↔ `PublicEvent` (frontend) ↔ `getPublicEvent` return — consistent across Tasks 5–7. `event.collection_code` used in both the schema (Task 5) and the page link (Task 7).

**Known follow-ups (documented, not gaps):** folding `getJoinConfig` into `getPublicEvent`; dropping the redundant response `status` field (already omitted — endpoint signals expiry via HTTP 410); token-enumeration hardening (orthogonal, tracked separately in the spec).
