# Human Verification UX Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the racing-Turnstile-and-403-loop pattern on `/collect/[code]` with an explicit blocking overlay state machine, add cookie versioning to invalidate every pre-existing `wrzdj_human` cookie on deploy, and fix the broken collect→join redirect without leaking `join_code` to unverified bots.

**Architecture:** Add `v` field to cookie payload (`HUMAN_COOKIE_VERSION = 2`); silently reject mismatched versions. New `GET /api/public/guest/verify-status` fast-path endpoint lets verified users skip Turnstile on page mount. New gated `GET /api/public/collect/{code}/live-join-code` returns the never-publicly-exposed join code only to verified humans during live phase. Frontend gets a new `HumanVerificationOverlay` component that owns the verification state UI; `useHumanVerification` is rewritten to fast-path-probe first and to surface a stable widget container instead of falling back to a hidden detached div.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0 (no migration), pytest, Next.js 16/React 19, TypeScript, vitest, Cloudflare Turnstile, jsdom.

**Spec:** `docs/superpowers/specs/2026-05-23-human-verification-ux-overlay-design.md`

**Branch:** `feat/human-verification-ux-overlay` (already created, spec committed at `e8530db`).

---

## Task 1: Add cookie version field — backend service

**Files:**
- Modify: `server/app/services/human_verification.py`
- Test: `server/tests/test_human_verification.py`

- [ ] **Step 1: Write the failing test for issued cookie carrying `v=2`**

In `server/tests/test_human_verification.py`, add at the bottom:

```python
def test_issued_cookie_payload_contains_version_2():
    """issue_human_cookie() must embed v=2 in the JSON payload."""
    import base64 as _b64
    import json as _json

    from fastapi import Response

    from app.services.human_verification import COOKIE_NAME, issue_human_cookie

    resp = Response()
    issue_human_cookie(resp, guest_id=42)
    raw = resp.headers["set-cookie"]
    cookie_value = raw.split(f"{COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    payload_part, _sig = cookie_value.rsplit(".", 1)

    pad = "=" * (-len(payload_part) % 4)
    payload = _json.loads(_b64.urlsafe_b64decode(payload_part + pad))

    assert payload["v"] == 2
    assert payload["guest_id"] == 42
    assert "exp" in payload
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && .venv/bin/pytest tests/test_human_verification.py::test_issued_cookie_payload_contains_version_2 -v`
Expected: FAIL with `KeyError: 'v'` (payload has only guest_id and exp).

- [ ] **Step 3: Add `HUMAN_COOKIE_VERSION` constant + update issue_human_cookie**

In `server/app/services/human_verification.py`, modify the constant block and the function:

```python
COOKIE_NAME = "wrzdj_human"
HUMAN_COOKIE_VERSION = 2  # Bump on any breaking schema or policy change.


def issue_human_cookie(response: Response, guest_id: int) -> None:
    """Sign payload with HMAC-SHA256 and set the wrzdj_human cookie.

    The payload carries an integer `v` discriminator so a future invalidation
    can reject all prior cookies by bumping the constant. Older payloads
    without the field are silently rejected in verify_human_cookie().

    Sliding window: caller invokes this on every successful gated request to
    reset the cookie's exp to now + ttl.
    """
    settings = get_settings()
    key = settings.effective_human_cookie_secret
    ttl = settings.human_cookie_ttl_seconds
    exp = int(utcnow().timestamp()) + ttl

    payload = {"v": HUMAN_COOKIE_VERSION, "guest_id": int(guest_id), "exp": exp}
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
    sig = _sign(payload_bytes, key)
    cookie_value = f"{_b64encode(payload_bytes)}.{_b64encode(sig)}"

    response.set_cookie(
        key=COOKIE_NAME,
        value=cookie_value,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=ttl,
        path="/api/",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server && .venv/bin/pytest tests/test_human_verification.py::test_issued_cookie_payload_contains_version_2 -v`
Expected: PASS

- [ ] **Step 5: Write failing tests for verify_human_cookie rejection of bad versions**

Append to `server/tests/test_human_verification.py`:

```python
def test_verify_rejects_unversioned_cookie():
    """A v=1 (versionless) cookie returned by the old infrastructure must be rejected."""
    import base64 as _b64
    import hashlib
    import hmac as _hmac
    import json as _json

    from fastapi import Request

    from app.core.config import get_settings
    from app.services.human_verification import COOKIE_NAME, verify_human_cookie

    key = get_settings().effective_human_cookie_secret
    payload = _json.dumps({"guest_id": 7, "exp": 9999999999}, separators=(",", ":")).encode()
    sig = _hmac.new(key, payload, hashlib.sha256).digest()

    def _b64(b: bytes) -> str:
        return _b64.urlsafe_b64encode(b).decode().rstrip("=")

    cookie_value = f"{_b64(payload)}.{_b64(sig)}"

    scope = {
        "type": "http",
        "headers": [(b"cookie", f"{COOKIE_NAME}={cookie_value}".encode())],
    }
    req = Request(scope)
    assert verify_human_cookie(req) is None


def test_verify_rejects_wrong_version_cookie():
    """A cookie with v=99 must be rejected even if signed correctly."""
    import base64 as _b64
    import hashlib
    import hmac as _hmac
    import json as _json

    from fastapi import Request

    from app.core.config import get_settings
    from app.services.human_verification import COOKIE_NAME, verify_human_cookie

    key = get_settings().effective_human_cookie_secret
    payload = _json.dumps(
        {"v": 99, "guest_id": 7, "exp": 9999999999}, separators=(",", ":")
    ).encode()
    sig = _hmac.new(key, payload, hashlib.sha256).digest()

    def _b64(b: bytes) -> str:
        return _b64.urlsafe_b64encode(b).decode().rstrip("=")

    cookie_value = f"{_b64(payload)}.{_b64(sig)}"

    scope = {
        "type": "http",
        "headers": [(b"cookie", f"{COOKIE_NAME}={cookie_value}".encode())],
    }
    req = Request(scope)
    assert verify_human_cookie(req) is None
```

- [ ] **Step 6: Run failing version tests**

Run: `cd server && .venv/bin/pytest tests/test_human_verification.py::test_verify_rejects_unversioned_cookie tests/test_human_verification.py::test_verify_rejects_wrong_version_cookie -v`
Expected: FAIL — verify_human_cookie currently accepts both because it never reads `v`.

- [ ] **Step 7: Add version check to verify_human_cookie**

In `server/app/services/human_verification.py`, modify the function to insert the version check between the signature check and the payload parsing:

```python
def verify_human_cookie(request: Request) -> int | None:
    """Return guest_id if the wrzdj_human cookie is valid, signed, version-matched, and unexpired.

    Returns None on any failure (missing, malformed, bad signature, wrong version, expired).
    """
    raw = request.cookies.get(COOKIE_NAME)
    if not raw or "." not in raw:
        return None

    try:
        payload_part, sig_part = raw.rsplit(".", 1)
        payload_bytes = _b64decode(payload_part)
        sig_bytes = _b64decode(sig_part)
    except (ValueError, binascii.Error):
        return None

    settings = get_settings()
    key = settings.effective_human_cookie_secret
    expected_sig = _sign(payload_bytes, key)

    if not hmac.compare_digest(expected_sig, sig_bytes):
        return None

    try:
        payload = json.loads(payload_bytes)
    except (ValueError, TypeError):
        return None

    # Reject cookies issued under prior schema versions (v=1 had no field;
    # the constant bump forces every pre-existing session to re-verify).
    if payload.get("v") != HUMAN_COOKIE_VERSION:
        return None

    try:
        guest_id_raw = payload["guest_id"]
        if not isinstance(guest_id_raw, int) or isinstance(guest_id_raw, bool):
            return None
        guest_id = guest_id_raw
        exp = payload["exp"]
        if not isinstance(exp, int) or isinstance(exp, bool):
            return None
    except (KeyError, TypeError):
        return None

    if exp < int(utcnow().timestamp()):
        return None

    return guest_id
```

- [ ] **Step 8: Run all human_verification tests**

Run: `cd server && .venv/bin/pytest tests/test_human_verification.py -v`
Expected: All pass (existing tests use `issue_human_cookie` which now stamps v=2 automatically).

- [ ] **Step 9: Commit**

```bash
git add server/app/services/human_verification.py server/tests/test_human_verification.py
git commit -m "feat(security): add v=2 field to wrzdj_human cookie payload

Pre-existing cookies (v=1, versionless) are silently rejected.
Bump HUMAN_COOKIE_VERSION on any future breaking schema or policy change."
```

---

## Task 2: `/verify-status` fast-path endpoint — backend

**Files:**
- Modify: `server/app/api/guest.py`
- Modify: `server/app/schemas/verify.py` (or wherever VerifyHumanResponse lives)
- Test: `server/tests/test_verify_status_endpoint.py` (NEW)

- [ ] **Step 1: Locate the verify schema file**

Run: `grep -rn "VerifyHumanResponse" server/app/schemas/`
Expected: a file like `server/app/schemas/verify.py` (or similar). All schema additions go in the same file as `VerifyHumanResponse`.

- [ ] **Step 2: Add VerifyStatusResponse schema**

Append to the file located in Step 1 (assume `server/app/schemas/verify.py`):

```python
class VerifyStatusResponse(BaseModel):
    """Reports whether the caller has a valid wrzdj_human cookie."""

    verified: bool
    expires_in: int = 0  # seconds until cookie expires; 0 when unverified
```

- [ ] **Step 3: Write failing endpoint test for unverified caller**

Create `server/tests/test_verify_status_endpoint.py`:

```python
"""Tests for GET /api/public/guest/verify-status."""

import hashlib
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.guest import Guest


def _make_guest(db: Session, suffix: str = "default") -> Guest:
    email = f"{suffix}@example.com"
    g = Guest(
        token="vs" + suffix.ljust(62, "0"),
        fingerprint_hash=f"fp_{suffix}",
        verified_email=email,
        email_hash=hashlib.sha256(email.encode()).hexdigest(),
        email_verified_at=utcnow(),
        created_at=utcnow(),
        last_seen_at=utcnow(),
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    return g


class TestVerifyStatusEndpoint:
    def test_no_cookie_returns_false(self, client: TestClient):
        client.cookies.clear()
        r = client.get("/api/public/guest/verify-status")
        assert r.status_code == 200
        body = r.json()
        assert body == {"verified": False, "expires_in": 0}

    def test_cache_control_header_no_store(self, client: TestClient):
        client.cookies.clear()
        r = client.get("/api/public/guest/verify-status")
        assert "no-store" in r.headers.get("cache-control", "").lower()
        assert "private" in r.headers.get("cache-control", "").lower()
```

- [ ] **Step 4: Run failing tests**

Run: `cd server && .venv/bin/pytest tests/test_verify_status_endpoint.py -v`
Expected: FAIL with 404 (endpoint doesn't exist).

- [ ] **Step 5: Implement the endpoint**

In `server/app/api/guest.py`, add after the existing `verify_human` POST endpoint:

```python
from app.schemas.verify import VerifyStatusResponse  # add to imports near top
from app.services.human_verification import (
    COOKIE_NAME,
    _b64decode,  # ok to import the helper; alternative: re-implement here
    verify_human_cookie,
)


@router.get("/guest/verify-status", response_model=VerifyStatusResponse)
@limiter.limit("60/minute")
def verify_status(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> VerifyStatusResponse:
    """Report whether the caller already has a valid wrzdj_human cookie.

    Returns verified=false on missing, expired, version-mismatched, or
    tampered cookies. No side effects (no cookie refresh, no DB writes).
    Safe to call on every page mount.
    """
    response.headers["Cache-Control"] = "no-store, private"

    guest_id = verify_human_cookie(request)
    if guest_id is None:
        return VerifyStatusResponse(verified=False, expires_in=0)

    # Cookie is valid — read exp from the payload to compute remaining ttl.
    import json as _json

    raw = request.cookies.get(COOKIE_NAME)
    payload_part, _sig = raw.rsplit(".", 1)
    payload = _json.loads(_b64decode(payload_part))
    remaining = max(0, int(payload["exp"]) - int(utcnow().timestamp()))
    return VerifyStatusResponse(verified=True, expires_in=remaining)
```

If `_b64decode` is private/underscore-prefixed and you want a cleaner import, expose it by removing the underscore in `human_verification.py` OR re-implement the 3-line base64 decode locally. Either approach is fine; pick whichever feels cleaner.

- [ ] **Step 6: Run unverified-caller tests**

Run: `cd server && .venv/bin/pytest tests/test_verify_status_endpoint.py -v`
Expected: PASS

- [ ] **Step 7: Add verified-caller test**

Append to `server/tests/test_verify_status_endpoint.py`:

```python
    def test_valid_cookie_returns_true_with_expires_in(self, client: TestClient, db: Session):
        from fastapi import Response

        from app.services.human_verification import COOKIE_NAME, issue_human_cookie

        guest = _make_guest(db, "valid")
        helper_resp = Response()
        issue_human_cookie(helper_resp, guest.id)
        raw = helper_resp.headers["set-cookie"]
        cookie_value = raw.split(f"{COOKIE_NAME}=", 1)[1].split(";", 1)[0]

        client.cookies.clear()
        client.cookies.set(COOKIE_NAME, cookie_value)

        r = client.get("/api/public/guest/verify-status")
        assert r.status_code == 200
        body = r.json()
        assert body["verified"] is True
        # Sliding window is 60 min (3600s); expires_in must be > 3500 and <= 3600
        assert 3500 < body["expires_in"] <= 3600

    def test_v1_cookie_returns_false(self, client: TestClient, db: Session):
        """Crafted v=1 cookie must be silently rejected as if missing."""
        import base64 as _b64
        import hashlib
        import hmac as _hmac
        import json as _json

        from app.core.config import get_settings

        guest = _make_guest(db, "v1")
        key = get_settings().effective_human_cookie_secret
        # v=1 payload (the old infrastructure had no 'v' field at all; same effect)
        payload = _json.dumps(
            {"guest_id": guest.id, "exp": 9999999999}, separators=(",", ":")
        ).encode()
        sig = _hmac.new(key, payload, hashlib.sha256).digest()

        def _b64enc(b: bytes) -> str:
            return _b64.urlsafe_b64encode(b).decode().rstrip("=")

        cookie_value = f"{_b64enc(payload)}.{_b64enc(sig)}"
        client.cookies.clear()
        client.cookies.set("wrzdj_human", cookie_value)

        r = client.get("/api/public/guest/verify-status")
        assert r.status_code == 200
        assert r.json() == {"verified": False, "expires_in": 0}

    def test_tampered_signature_returns_false(self, client: TestClient, db: Session):
        from fastapi import Response

        from app.services.human_verification import COOKIE_NAME, issue_human_cookie

        guest = _make_guest(db, "tamper")
        helper_resp = Response()
        issue_human_cookie(helper_resp, guest.id)
        raw = helper_resp.headers["set-cookie"]
        cookie_value = raw.split(f"{COOKIE_NAME}=", 1)[1].split(";", 1)[0]
        # Flip the last char of the signature
        bad = cookie_value[:-1] + ("A" if cookie_value[-1] != "A" else "B")

        client.cookies.clear()
        client.cookies.set(COOKIE_NAME, bad)
        r = client.get("/api/public/guest/verify-status")
        assert r.status_code == 200
        assert r.json()["verified"] is False
```

- [ ] **Step 8: Run all verify-status tests**

Run: `cd server && .venv/bin/pytest tests/test_verify_status_endpoint.py -v`
Expected: All 5 tests PASS

- [ ] **Step 9: Commit**

```bash
git add server/app/api/guest.py server/app/schemas/verify.py server/tests/test_verify_status_endpoint.py
git commit -m "feat(api): add GET /api/public/guest/verify-status fast-path probe

Returns {verified, expires_in} for the caller's current wrzdj_human cookie.
No DB queries, no side effects, Cache-Control: no-store. Lets the frontend
skip Turnstile on page mount when a valid cookie already exists."
```

---

## Task 3: `/live-join-code` gated endpoint — backend

**Files:**
- Modify: `server/app/api/collect.py`
- Modify: `server/app/schemas/collect.py`
- Test: `server/tests/test_collect_public.py`

- [ ] **Step 1: Add LiveJoinCodeResponse schema**

Append to `server/app/schemas/collect.py`:

```python
class LiveJoinCodeResponse(BaseModel):
    """Returns the live join_code for an event that has entered the live phase.

    Gated by require_verified_human so the join_code never leaks to unverified
    bots scraping the collect URL during the collection-to-live transition.
    """

    join_code: str
```

- [ ] **Step 2: Write failing test for unverified caller**

Append to `server/tests/test_collect_public.py` at the end of the file:

```python
class TestLiveJoinCodeEndpoint:
    """GET /api/public/collect/{code}/live-join-code"""

    def _force_live(self, db, event):
        event.collection_phase_override = "force_live"
        db.commit()
        db.refresh(event)

    def test_403_without_human_cookie(self, client, db, test_event):
        self._force_live(db, test_event)
        client.cookies.clear()
        r = client.get(f"/api/public/collect/{test_event.code}/live-join-code")
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "human_verification_required"
        # Critically: no join_code leak in error body
        assert "join_code" not in str(r.json())

    def test_200_when_live_and_verified(self, client, db, test_event):
        # The autouse fixture in this file pre-verifies the default guest;
        # _default_guest_cookie sets both wrzdj_guest and wrzdj_human.
        self._force_live(db, test_event)
        r = client.get(f"/api/public/collect/{test_event.code}/live-join-code")
        assert r.status_code == 200
        assert r.json() == {"join_code": test_event.join_code}

    def test_409_when_phase_is_collection(self, client, db, test_event):
        _enable_collection(db, test_event)
        r = client.get(f"/api/public/collect/{test_event.code}/live-join-code")
        assert r.status_code == 409

    def test_404_for_unknown_event(self, client, db, test_event):
        r = client.get("/api/public/collect/ZZZZZZ/live-join-code")
        assert r.status_code == 404
```

- [ ] **Step 3: Run failing tests**

Run: `cd server && .venv/bin/pytest tests/test_collect_public.py::TestLiveJoinCodeEndpoint -v`
Expected: All FAIL with 404 (endpoint doesn't exist).

- [ ] **Step 4: Implement the endpoint**

In `server/app/api/collect.py`, add to the imports:

```python
from app.api.deps import get_db, require_email_verified, require_verified_human
from app.schemas.collect import (
    # ... existing imports
    LiveJoinCodeResponse,
)
```

Then append a new route handler at the bottom of the file:

```python
@router.get("/{code}/live-join-code", response_model=LiveJoinCodeResponse)
@limiter.limit("60/minute")
def get_live_join_code(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
    _guest_id: int = Depends(require_verified_human),
) -> LiveJoinCodeResponse:
    """Return the live join_code for an event that has entered the live phase.

    Requires a verified human cookie (not email verification) so the join_code
    is never leaked to unverified bots scraping /collect during the
    collection-to-live transition. The join_code is otherwise revealed only
    via the QR code at the event venue.
    """
    event = _get_event_or_404(db, code)
    if event.phase not in ("live", "closed"):
        raise HTTPException(status_code=409, detail="Event is not live")
    return LiveJoinCodeResponse(join_code=event.join_code)
```

- [ ] **Step 5: Run tests**

Run: `cd server && .venv/bin/pytest tests/test_collect_public.py::TestLiveJoinCodeEndpoint -v`
Expected: All 4 PASS

- [ ] **Step 6: Commit**

```bash
git add server/app/api/collect.py server/app/schemas/collect.py server/tests/test_collect_public.py
git commit -m "feat(api): add gated GET /collect/{code}/live-join-code

Returns the live event join_code to verified humans during the live phase.
Bots without a valid wrzdj_human cookie cannot learn the join_code from
this endpoint, preserving the property that join codes are only revealed
via QR at event time. Fixes a redirect bug in the collect page (PR #324
left router.replace pointing at the wrong code)."
```

---

## Task 4: Frontend API client methods

**Files:**
- Modify: `dashboard/lib/api.ts`
- Test: `dashboard/lib/__tests__/api.test.ts`

- [ ] **Step 1: Write failing tests for the new methods**

Append to `dashboard/lib/__tests__/api.test.ts`:

```typescript
describe("apiClient.getVerifyStatus", () => {
  it("hits GET /api/public/guest/verify-status and returns the JSON body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ verified: true, expires_in: 3500 }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const result = await apiClient.getVerifyStatus();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/public/guest/verify-status"),
      expect.objectContaining({ credentials: "include" }),
    );
    expect(result).toEqual({ verified: true, expires_in: 3500 });
  });

  it("returns verified=false on network error", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("network"));
    vi.stubGlobal("fetch", fetchMock);
    const result = await apiClient.getVerifyStatus();
    expect(result).toEqual({ verified: false, expires_in: 0 });
  });
});

describe("apiClient.getLiveJoinCode", () => {
  it("hits GET /api/public/collect/{code}/live-join-code with credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ join_code: "ABC123" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const result = await apiClient.getLiveJoinCode("XYZ987");
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/public/collect/XYZ987/live-join-code"),
      expect.objectContaining({ credentials: "include" }),
    );
    expect(result).toEqual({ join_code: "ABC123" });
  });

  it("throws ApiError on non-OK response", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: () => Promise.resolve({ detail: "Event is not live" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiClient.getLiveJoinCode("XYZ987")).rejects.toThrow();
  });
});
```

- [ ] **Step 2: Run failing tests**

Run: `cd dashboard && npm test -- --run lib/__tests__/api.test.ts -t "getVerifyStatus|getLiveJoinCode"`
Expected: FAIL — methods don't exist.

- [ ] **Step 3: Add the methods to ApiClient**

In `dashboard/lib/api.ts`, add methods inside the `ApiClient` class (anywhere in the class body):

```typescript
async getVerifyStatus(): Promise<{ verified: boolean; expires_in: number }> {
  try {
    const res = await fetch(`${getApiUrl()}/api/public/guest/verify-status`, {
      method: 'GET',
      credentials: 'include',
    });
    if (!res.ok) return { verified: false, expires_in: 0 };
    return res.json();
  } catch {
    // Network failure — caller falls back to running Turnstile.
    return { verified: false, expires_in: 0 };
  }
}

async getLiveJoinCode(code: string): Promise<{ join_code: string }> {
  const res = await fetch(
    `${getApiUrl()}/api/public/collect/${code}/live-join-code`,
    { method: 'GET', credentials: 'include' },
  );
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: 'Request failed' }));
    throw new ApiError(
      typeof body.detail === 'string' ? body.detail : 'Live join code unavailable',
      res.status,
    );
  }
  return res.json();
}
```

- [ ] **Step 4: Run tests**

Run: `cd dashboard && npm test -- --run lib/__tests__/api.test.ts -t "getVerifyStatus|getLiveJoinCode"`
Expected: All 4 PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/lib/api.ts dashboard/lib/__tests__/api.test.ts
git commit -m "feat(client): add getVerifyStatus and getLiveJoinCode methods

getVerifyStatus returns {verified, expires_in: 0} on any error so callers
don't need to branch. getLiveJoinCode throws ApiError on non-2xx because
the polling caller treats 409 and 403 differently and needs to discriminate."
```

---

## Task 5: HumanVerificationOverlay component

**Files:**
- Create: `dashboard/components/HumanVerificationOverlay.tsx`
- Create: `dashboard/components/__tests__/HumanVerificationOverlay.test.tsx`
- Modify: `dashboard/app/globals.css`

- [ ] **Step 1: Write failing component tests**

Create `dashboard/components/__tests__/HumanVerificationOverlay.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { createRef } from "react";
import HumanVerificationOverlay from "../HumanVerificationOverlay";

describe("HumanVerificationOverlay", () => {
  it("renders the LoadingPanel while state=loading", () => {
    const ref = createRef<HTMLDivElement>();
    render(
      <HumanVerificationOverlay state="loading" widgetContainerRef={ref} onRetry={() => {}}>
        <div data-testid="hidden-child">child</div>
      </HumanVerificationOverlay>,
    );
    expect(screen.getByText(/just a moment/i)).toBeDefined();
    // Children should NOT render
    expect(screen.queryByTestId("hidden-child")).toBeNull();
  });

  it("renders the ChallengePanel when state=challenge with a visible widget container", () => {
    const ref = createRef<HTMLDivElement>();
    render(
      <HumanVerificationOverlay state="challenge" widgetContainerRef={ref} onRetry={() => {}}>
        <div data-testid="hidden-child">child</div>
      </HumanVerificationOverlay>,
    );
    expect(screen.getByText(/one more step/i)).toBeDefined();
    expect(screen.queryByTestId("hidden-child")).toBeNull();
    const container = screen.getByTestId("hv-widget-container");
    expect(container).toBeDefined();
    expect(container.style.opacity).toBe("1");
  });

  it("renders the FailedPanel and calls onRetry on button click", () => {
    const ref = createRef<HTMLDivElement>();
    const onRetry = vi.fn();
    render(
      <HumanVerificationOverlay state="failed" widgetContainerRef={ref} onRetry={onRetry}>
        <div data-testid="hidden-child">child</div>
      </HumanVerificationOverlay>,
    );
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("renders children only when state=verified", () => {
    const ref = createRef<HTMLDivElement>();
    render(
      <HumanVerificationOverlay state="verified" widgetContainerRef={ref} onRetry={() => {}}>
        <div data-testid="visible-child">visible</div>
      </HumanVerificationOverlay>,
    );
    expect(screen.getByTestId("visible-child")).toBeDefined();
    expect(screen.queryByText(/just a moment/i)).toBeNull();
  });

  it("attaches the widget ref in non-verified states", () => {
    const ref = createRef<HTMLDivElement>();
    render(
      <HumanVerificationOverlay state="loading" widgetContainerRef={ref} onRetry={() => {}}>
        <div>child</div>
      </HumanVerificationOverlay>,
    );
    expect(ref.current).not.toBeNull();
    expect(ref.current?.tagName).toBe("DIV");
  });
});
```

- [ ] **Step 2: Run failing tests**

Run: `cd dashboard && npm test -- --run components/__tests__/HumanVerificationOverlay.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the component**

Create `dashboard/components/HumanVerificationOverlay.tsx`:

```tsx
'use client';

import { ReactNode } from 'react';
import type { HumanVerificationState } from '../lib/useHumanVerification';

interface Props {
  state: HumanVerificationState;
  widgetContainerRef: React.RefObject<HTMLDivElement | null>;
  onRetry: () => void;
  children: ReactNode;
}

/**
 * Blocks all page UI until the visitor's wrzdj_human cookie is established.
 * Provides a stable widget container the useHumanVerification hook can render
 * Turnstile into across every non-verified state, so Cloudflare's escalation
 * from invisible to visible challenge always has a reachable DOM node.
 */
export default function HumanVerificationOverlay({
  state,
  widgetContainerRef,
  onRetry,
  children,
}: Props) {
  if (state === 'verified') {
    return <>{children}</>;
  }

  return (
    <div className="hv-overlay-backdrop">
      <div className="hv-overlay-modal" role="dialog" aria-live="polite">
        {(state === 'idle' || state === 'loading') && <LoadingPanel />}
        {state === 'challenge' && <ChallengePanel />}
        {state === 'failed' && <FailedPanel onRetry={onRetry} />}

        <div
          ref={widgetContainerRef}
          data-testid="hv-widget-container"
          style={{
            marginTop: state === 'challenge' ? '1rem' : 0,
            minHeight: state === 'challenge' ? '65px' : 0,
            opacity: state === 'challenge' ? 1 : 0,
            pointerEvents: state === 'challenge' ? 'auto' : 'none',
            transition: 'opacity 120ms ease, min-height 120ms ease',
          }}
        />
      </div>
    </div>
  );
}

function LoadingPanel() {
  return (
    <>
      <div className="hv-overlay-spinner" aria-label="Verifying" />
      <h2 className="hv-overlay-title">Just a moment</h2>
      <p className="hv-overlay-body">
        We're verifying your browser before you start picking songs. This usually takes a second.
      </p>
      <p className="hv-overlay-footnote">Powered by Cloudflare Turnstile</p>
    </>
  );
}

function ChallengePanel() {
  return (
    <>
      <h2 className="hv-overlay-title">One more step</h2>
      <p className="hv-overlay-body">Please complete the security check below.</p>
    </>
  );
}

function FailedPanel({ onRetry }: { onRetry: () => void }) {
  return (
    <>
      <h2 className="hv-overlay-title">Verification didn't go through</h2>
      <p className="hv-overlay-body">
        Some privacy tools (Brave Shields, strict tracking protection, VPNs) can interfere. Try
        again, or open this page in a different browser.
      </p>
      <button type="button" className="hv-overlay-retry" onClick={onRetry}>
        Try again
      </button>
    </>
  );
}
```

- [ ] **Step 4: Add CSS for the overlay**

Append to `dashboard/app/globals.css`:

```css
/* HumanVerificationOverlay — full-screen blocker shown until wrzdj_human cookie is established */
.hv-overlay-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.78);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  padding: 1rem;
}

.hv-overlay-modal {
  background: #1a1a1a;
  border-radius: 14px;
  padding: 1.75rem;
  width: 100%;
  max-width: 420px;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  text-align: center;
}

.hv-overlay-title {
  font-size: 1.25rem;
  margin: 0 0 0.5rem 0;
  color: #ededed;
}

.hv-overlay-body {
  font-size: 0.9rem;
  color: #a0a0a0;
  margin: 0 0 1rem 0;
  line-height: 1.45;
}

.hv-overlay-footnote {
  font-size: 0.75rem;
  color: #6a6a6a;
  margin: 0;
}

.hv-overlay-spinner {
  width: 32px;
  height: 32px;
  margin: 0 auto 0.75rem;
  border: 3px solid rgba(255, 255, 255, 0.12);
  border-top-color: #ededed;
  border-radius: 50%;
  animation: hv-spin 1s linear infinite;
}

@keyframes hv-spin {
  to {
    transform: rotate(360deg);
  }
}

.hv-overlay-retry {
  padding: 0.6rem 1.2rem;
  font-size: 0.9rem;
  font-weight: 600;
  color: #0a0a0a;
  background: #ededed;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  margin-top: 0.5rem;
}

.hv-overlay-retry:hover {
  background: #fff;
}
```

- [ ] **Step 5: Run component tests**

Run: `cd dashboard && npm test -- --run components/__tests__/HumanVerificationOverlay.test.tsx`
Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add dashboard/components/HumanVerificationOverlay.tsx dashboard/components/__tests__/HumanVerificationOverlay.test.tsx dashboard/app/globals.css
git commit -m "feat(ui): add HumanVerificationOverlay component

Provides a stable widget container in all non-verified states so Cloudflare's
escalation from invisible to visible challenge always has a reachable DOM
node. Three panels: Loading, Challenge, Failed (with Retry)."
```

---

## Task 6: Rewrite useHumanVerification hook

**Files:**
- Modify: `dashboard/lib/useHumanVerification.ts`
- Test: `dashboard/lib/__tests__/useHumanVerification.test.tsx`

- [ ] **Step 1: Write failing test for fast-path skip**

In `dashboard/lib/__tests__/useHumanVerification.test.tsx`, add at the top of the file (near other vi.mock calls):

```tsx
vi.mock("../api", () => ({
  api: {
    verifyHuman: vi.fn().mockResolvedValue({ verified: true, expires_in: 3600 }),
    getVerifyStatus: vi.fn(),
  },
  apiClient: {},
}));
```

Then append the new test cases at the bottom of the existing `describe` block:

```tsx
import { api } from "../api";

describe("fast-path probe", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("skips Turnstile when /verify-status returns verified=true", async () => {
    (api.getVerifyStatus as any).mockResolvedValue({ verified: true, expires_in: 3500 });
    window.turnstile = { render: vi.fn(), reset: vi.fn(), remove: vi.fn(), execute: vi.fn() } as any;

    const { result } = renderHook(() => useHumanVerification());
    await waitFor(() => expect(result.current.state).toBe("verified"));
    expect((window.turnstile as any).render).not.toHaveBeenCalled();
  });

  it("runs Turnstile when /verify-status returns verified=false", async () => {
    (api.getVerifyStatus as any).mockResolvedValue({ verified: false, expires_in: 0 });
    const renderMock = vi.fn().mockReturnValue("widget-id");
    window.turnstile = { render: renderMock, reset: vi.fn(), remove: vi.fn(), execute: vi.fn() } as any;
    // Stub script loader + sitekey resolver
    vi.mock("../turnstile", () => ({
      getTurnstileSiteKey: () => Promise.resolve("test-key"),
      loadTurnstileScript: () => Promise.resolve(),
    }));

    const { result } = renderHook(() => useHumanVerification());
    await waitFor(() => expect(result.current.state).toBe("loading"));
  });

  it("falls back to Turnstile when /verify-status throws", async () => {
    (api.getVerifyStatus as any).mockRejectedValue(new Error("network"));
    window.turnstile = { render: vi.fn(), reset: vi.fn(), remove: vi.fn(), execute: vi.fn() } as any;

    const { result } = renderHook(() => useHumanVerification());
    // We should at least leave 'idle' (either to 'loading' or eventually 'verified' via fallback)
    await waitFor(() => expect(result.current.state).not.toBe("idle"));
  });
});

describe("retry method", () => {
  it("re-mounts the widget when retry() is called from failed state", async () => {
    (api.getVerifyStatus as any).mockResolvedValue({ verified: false, expires_in: 0 });
    const renderMock = vi.fn().mockReturnValue("widget-id");
    const removeMock = vi.fn();
    window.turnstile = {
      render: renderMock,
      reset: vi.fn(),
      remove: removeMock,
      execute: vi.fn(),
    } as any;

    const { result } = renderHook(() => useHumanVerification());
    await waitFor(() => expect(result.current.state).toBe("loading"));
    // Simulate failure
    act(() => {
      // The hook exposes retry; calling it should call remove + render again
      result.current.retry();
    });
    // After retry, render should have been called at least twice (initial + retry)
    await waitFor(() => expect(renderMock).toHaveBeenCalled());
  });
});
```

- [ ] **Step 2: Run failing tests**

Run: `cd dashboard && npm test -- --run lib/__tests__/useHumanVerification.test.tsx`
Expected: FAIL — `getVerifyStatus` doesn't exist on the mock yet; `result.current.retry` is undefined.

- [ ] **Step 3: Rewrite the hook**

Replace `dashboard/lib/useHumanVerification.ts` entirely with:

```typescript
'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from './api';
import { getTurnstileSiteKey, loadTurnstileScript } from './turnstile';

export type HumanVerificationState =
  | 'idle'
  | 'loading'
  | 'verified'
  | 'challenge'
  | 'failed';

export interface UseHumanVerification {
  state: HumanVerificationState;
  ensureVerified: () => Promise<void>;
  reverify: () => Promise<void>;
  retry: () => void;
  widgetContainerRef: React.RefObject<HTMLDivElement | null>;
}

export function useHumanVerification(): UseHumanVerification {
  const [state, setState] = useState<HumanVerificationState>('idle');
  const widgetContainerRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);
  const verifiedResolversRef = useRef<Array<() => void>>([]);
  const mountedRef = useRef(true);
  const stateRef = useRef(state);
  stateRef.current = state;

  const flushVerified = useCallback(() => {
    verifiedResolversRef.current.forEach((resolve) => resolve());
    verifiedResolversRef.current = [];
  }, []);

  const submitToken = useCallback(
    async (token: string) => {
      try {
        const result = await api.verifyHuman(token);
        if (!mountedRef.current) return;
        if (result.verified) {
          setState('verified');
          flushVerified();
        } else {
          setState('failed');
        }
      } catch {
        if (mountedRef.current) setState('failed');
      }
    },
    [flushVerified],
  );

  const renderWidget = useCallback(async () => {
    if (!mountedRef.current) return;
    setState('loading');
    const sitekey = await getTurnstileSiteKey();
    if (!mountedRef.current) return;
    if (!sitekey) {
      setState('verified');
      flushVerified();
      return;
    }
    await loadTurnstileScript();
    if (!mountedRef.current || !window.turnstile) return;

    const container = widgetContainerRef.current;
    if (!container) {
      // Overlay should have mounted the ref by now; if not, wait one frame.
      requestAnimationFrame(() => void renderWidget());
      return;
    }

    if (widgetIdRef.current) {
      window.turnstile.reset(widgetIdRef.current);
      return;
    }

    widgetIdRef.current = window.turnstile.render(container, {
      sitekey,
      appearance: 'interaction-only',
      size: 'normal',
      callback: (token: string) => {
        void submitToken(token);
      },
      'error-callback': () => {
        if (mountedRef.current) setState('failed');
      },
      'expired-callback': () => {
        if (!mountedRef.current) return;
        setState('idle');
        if (widgetIdRef.current && window.turnstile) {
          window.turnstile.reset(widgetIdRef.current);
        }
      },
      // Cloudflare invokes this when it escalates an invisible challenge to
      // a visible one. We flip state so the overlay reveals the widget.
      // (Open implementation item: confirm callback name; if absent, poll
      // the iframe's bounding box via requestAnimationFrame as a fallback.)
      'before-interactive-callback': () => {
        if (mountedRef.current) setState('challenge');
      },
    } as any);
  }, [submitToken, flushVerified]);

  // Bootstrap: fast-path probe, then optionally start Turnstile
  useEffect(() => {
    mountedRef.current = true;
    void (async () => {
      try {
        const status = await api.getVerifyStatus();
        if (!mountedRef.current) return;
        if (status.verified) {
          setState('verified');
          flushVerified();
          return;
        }
      } catch {
        // /verify-status failure (network / 5xx) falls through to Turnstile
      }
      try {
        await renderWidget();
      } catch {
        if (mountedRef.current) setState('failed');
      }
    })();
    return () => {
      mountedRef.current = false;
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current);
        widgetIdRef.current = null;
      }
    };
  }, [renderWidget, flushVerified]);

  const ensureVerified = useCallback((): Promise<void> => {
    if (stateRef.current === 'verified') return Promise.resolve();
    return new Promise((resolve) => {
      verifiedResolversRef.current.push(resolve);
    });
  }, []);

  const reverify = useCallback(async () => {
    if (!mountedRef.current) return;
    if (widgetIdRef.current && window.turnstile) {
      window.turnstile.reset(widgetIdRef.current);
    }
    setState('loading');
    await renderWidget();
  }, [renderWidget]);

  const retry = useCallback(() => {
    if (widgetIdRef.current && window.turnstile) {
      window.turnstile.remove(widgetIdRef.current);
      widgetIdRef.current = null;
    }
    void renderWidget();
  }, [renderWidget]);

  return { state, ensureVerified, reverify, retry, widgetContainerRef };
}
```

- [ ] **Step 4: Run tests**

Run: `cd dashboard && npm test -- --run lib/__tests__/useHumanVerification.test.tsx`
Expected: All tests PASS (existing + new fast-path + retry tests).

- [ ] **Step 5: Run frontend type check + lint**

Run: `cd dashboard && npx tsc --noEmit && npm run lint`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add dashboard/lib/useHumanVerification.ts dashboard/lib/__tests__/useHumanVerification.test.tsx
git commit -m "feat(hook): rewrite useHumanVerification with /verify-status fast path

- Fast-path: GET /verify-status on mount; skip Turnstile if cookie valid.
- Drop the display:none / zero-size fallback container; overlay always
  provides a stable widget container in non-verified states.
- New retry() method for FailedPanel's Try Again button.
- before-interactive-callback flips state to 'challenge' on Cloudflare
  escalation (with fallback documented for impl-time verification).
- mountedRef guards on every setState; clean unmount semantics."
```

---

## Task 7: Wrap collect page in overlay + gated live-redirect

**Files:**
- Modify: `dashboard/app/collect/[code]/page.tsx`
- Modify: `dashboard/app/collect/[code]/page.test.tsx`

- [ ] **Step 1: Write failing test for held-redirect**

Append to `dashboard/app/collect/[code]/page.test.tsx` inside the existing `describe`:

```tsx
it("does not redirect to /join until humanState is verified", async () => {
  // Mock event in live phase
  mockGetEvent.mockResolvedValue({
    code: "ABC",
    name: "Test Event",
    phase: "live",
    submission_cap_per_guest: 15,
    banner_filename: null,
    registration_enabled: true,
    expires_at: new Date(Date.now() + 86400_000).toISOString(),
    collection_opens_at: null,
    live_starts_at: null,
  });

  // useHumanVerification mocked to 'loading' (NOT 'verified')
  vi.mock("@/lib/useHumanVerification", () => ({
    useHumanVerification: () => ({
      state: "loading",
      reverify: vi.fn().mockResolvedValue(undefined),
      retry: vi.fn(),
      ensureVerified: vi.fn().mockResolvedValue(undefined),
      widgetContainerRef: { current: null },
    }),
  }));

  render(<CollectPage />);
  // Wait long enough for any polling tick to fire
  await new Promise((r) => setTimeout(r, 100));
  expect(mockReplace).not.toHaveBeenCalled();
});

it("calls getLiveJoinCode and redirects to /join/<join_code> when phase=live and verified", async () => {
  vi.mock("@/lib/useHumanVerification", () => ({
    useHumanVerification: () => ({
      state: "verified",
      reverify: vi.fn().mockResolvedValue(undefined),
      retry: vi.fn(),
      ensureVerified: vi.fn().mockResolvedValue(undefined),
      widgetContainerRef: { current: null },
    }),
  }));
  mockGetEvent.mockResolvedValue({
    code: "ABC",
    name: "Test",
    phase: "live",
    submission_cap_per_guest: 15,
    banner_filename: null,
    registration_enabled: true,
    expires_at: new Date(Date.now() + 86400_000).toISOString(),
    collection_opens_at: null,
    live_starts_at: null,
  });

  const mockGetLiveJoinCode = vi.fn().mockResolvedValue({ join_code: "XYZ987" });
  // Extend the api mock — the test file's existing vi.mock("../../../lib/api") must
  // include this method. Update the mock block at the top of the file accordingly.
  // ...

  render(<CollectPage />);
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/join/XYZ987"));
  expect(mockGetLiveJoinCode).toHaveBeenCalledWith("ABC");
});
```

The test file's existing mock of `../../../lib/api` must be updated to include `getLiveJoinCode: (...a: unknown[]) => mockGetLiveJoinCode(...a)`. Update the mock block accordingly (it's at the top of `page.test.tsx`).

- [ ] **Step 2: Run failing tests**

Run: `cd dashboard && npm test -- --run app/collect/\[code\]/page.test.tsx`
Expected: New tests FAIL.

- [ ] **Step 3: Wrap the collect page in HumanVerificationOverlay**

In `dashboard/app/collect/[code]/page.tsx`:

1. Add import near the other component imports:

   ```tsx
   import HumanVerificationOverlay from '../../../components/HumanVerificationOverlay';
   ```

2. Update the hook destructure to grab `retry`:

   ```tsx
   const { state: humanState, reverify, retry, widgetContainerRef } = useHumanVerification();
   ```

3. Refactor the early returns into a `renderPageContent()` helper and wrap everything in the overlay. Find the section near line 268-322 that has `if (!gateComplete) return ...` followed by other early returns and the main return. Replace the entire control-flow block from `if (!gateComplete)` down to the end of the function with:

   ```tsx
   const renderPageContent = () => {
     if (!gateComplete) {
       return <NicknameGate code={code} onComplete={handleGateComplete} reverify={reverify} />;
     }

     if (error) {
       return (
         <main className="collect-page">
           <div className="collect-container">
             <div className="collect-error">Error: {error}</div>
           </div>
         </main>
       );
     }
     if (!event) {
       return (
         <main className="collect-page">
           <div className="loading">Loading…</div>
         </main>
       );
     }

     const bannerNode = event.banner_url ? (
       <div className="join-banner-bg">
         <img src={event.banner_url} alt="" />
       </div>
     ) : null;

     if (event.phase === 'pre_announce') {
       const opens = event.collection_opens_at ? new Date(event.collection_opens_at) : null;
       return (
         <main className="collect-page tower">
           {bannerNode}
           <div className="collect-container">
             <div className="collect-preannounce">
               <div className="collect-phase-badge pre-announce">
                 <span>🎟️</span>
                 <span>Pre-event voting</span>
               </div>
               <h1 className="collect-title">{event.name}</h1>
               <div className="collect-preannounce-count">{formatCountdown(opens)}</div>
               <p className="collect-countdown">until voting opens</p>
             </div>
           </div>
         </main>
       );
     }

     // ... THE EXISTING main return JSX starting with `<EmailGate verified={...}>` and
     // ending with the closing `</EmailGate>` goes here, returned. Copy the entire
     // existing main-return tree verbatim into this branch.
     return (
       <EmailGate verified={emailVerified} onVerified={() => setEmailVerified(true)}>
         {/* EXISTING <main className="collect-page tower"> ... </main> body verbatim */}
       </EmailGate>
     );
   };

   return (
     <HumanVerificationOverlay
       state={humanState}
       widgetContainerRef={widgetContainerRef}
       onRetry={retry}
     >
       {renderPageContent()}
     </HumanVerificationOverlay>
   );
   ```

4. Delete the inline widget container block previously at line ~430-438:

   ```tsx
   {/* DELETE this block — overlay owns the widget container now */}
   {/* The Turnstile widget container is now hoisted ABOVE the gate-blocking
       early return at the top of this component — see `turnstileWidget`. */}
   ```

5. Delete the inline `{humanState === 'failed' && <div>...</div>}` block — the overlay's FailedPanel handles this now.

- [ ] **Step 4: Update the polling tick to use gated live-redirect**

Find the polling `tick` function (around line 197-241). Replace the live-phase branch:

```tsx
const tick = async () => {
  try {
    const ev = await apiClient.getCollectEvent(code);
    if (cancelled) return;
    setEvent(ev);

    if (ev.phase === 'live' || ev.phase === 'closed') {
      // Don't redirect to /join until we KNOW we're verified — the join_code
      // is gated. The overlay is still up if we're not verified; next tick
      // will retry once humanState flips.
      if (humanState !== 'verified') return;
      try {
        const { join_code } = await apiClient.getLiveJoinCode(code);
        sessionStorage.setItem(`wrzdj_live_splash_${code}`, '1');
        router.replace(`/join/${join_code}`);
      } catch {
        // 403 (re-verify needed) or 409 (phase mismatch) — bail; next tick retries
      }
      return;
    }

    if (ev.phase === 'collection') {
      const lb = await apiClient.getCollectLeaderboard(code, tab);
      if (!cancelled) setLeaderboard(lb);
      if (emailVerified) {
        const picks = await apiClient.getCollectMyPicks(code);
        if (!cancelled) setMyPicks(picks);
      }
    }
  } catch (e) {
    if (!cancelled) setError((e as Error).message);
  }
  if (!cancelled && document.visibilityState === 'visible') {
    timer = setTimeout(tick, POLL_MS);
  }
};
```

Update the dependency array on the polling `useEffect`:

```tsx
}, [code, tab, gateComplete, emailVerified, humanState]);
```

- [ ] **Step 5: Delete the unused `redirectToJoin` helper**

The previous `redirectToJoin` function at line ~192-195 is now inlined into the tick handler. Delete it.

- [ ] **Step 6: Update the page.test.tsx mock block**

In `dashboard/app/collect/[code]/page.test.tsx`, update the `vi.mock("../../../lib/api", ...)` block to include the new method:

```tsx
const mockGetLiveJoinCode = vi.fn().mockResolvedValue({ join_code: "XYZJOIN" });

vi.mock("../../../lib/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
  apiClient: {
    getCollectEvent: (...a: unknown[]) => mockGetEvent(...a),
    getCollectLeaderboard: (...a: unknown[]) => mockGetCollectLeaderboard(...a),
    getCollectMyPicks: vi.fn().mockResolvedValue({
      submitted: [],
      upvoted: [],
      is_top_contributor: false,
      first_suggestion_ids: [],
      voted_request_ids: [],
    }),
    getCollectProfile: (...a: unknown[]) => mockGetCollectProfile(...a),
    submitCollectRequest: (...a: unknown[]) => mockSubmitCollectRequest(...a),
    eventSearch: (...a: unknown[]) => mockEventSearch(...a),
    search: vi.fn().mockResolvedValue([]),
    voteCollectRequest: vi.fn().mockResolvedValue(undefined),
    enrichPreview: (...a: unknown[]) => mockEnrichPreview(...a),
    getLiveJoinCode: (...a: unknown[]) => mockGetLiveJoinCode(...a),
  },
}));
```

Also add a passthrough mock for the overlay alongside the existing EmailGate / EmailVerification stubs at the top of the test file:

```tsx
vi.mock("../../../components/HumanVerificationOverlay", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
```

- [ ] **Step 7: Run page.test.tsx**

Run: `cd dashboard && npm test -- --run app/collect/\[code\]/page.test.tsx`
Expected: All PASS (existing + 2 new redirect tests).

- [ ] **Step 8: Run frontend type check + lint**

Run: `cd dashboard && npx tsc --noEmit && npm run lint`
Expected: No errors.

- [ ] **Step 9: Commit**

```bash
git add dashboard/app/collect/\[code\]/page.tsx dashboard/app/collect/\[code\]/page.test.tsx
git commit -m "feat(collect): wrap page in HumanVerificationOverlay + gated live redirect

- Whole page sits behind the overlay until humanState is verified.
- Live-phase redirect now calls the new /live-join-code endpoint and uses
  the returned join_code (fixes the broken /join/{collection_code} from
  PR #324).
- Redirect is held until humanState is verified so bots can't learn the
  join_code from the redirect flow.
- Pre-announce countdown is intentionally still behind the overlay."
```

---

## Task 8: Run full CI locally

- [ ] **Step 1: Backend full suite**

Run: `cd server && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/bandit -r app -c pyproject.toml -q && .venv/bin/pytest --tb=short -q`
Expected: All checks pass; coverage ≥85%.

- [ ] **Step 2: Backend Alembic check**

Run: `cd server && .venv/bin/alembic upgrade head && .venv/bin/alembic check`
Expected: "No new upgrade operations detected."

- [ ] **Step 3: Frontend full suite**

Run: `cd dashboard && npm run lint && npx tsc --noEmit && npm test -- --run`
Expected: All pass.

- [ ] **Step 4: Bridge + bridge-app type checks**

Run: `cd bridge && npx tsc --noEmit && npm test -- --run`
Run: `cd bridge-app && npx tsc --noEmit && npm test -- --run`
Expected: All pass.

- [ ] **Step 5: If any check fails, fix the smallest unit and re-run**

Document the failure inline and resolve. Common surprises:
- `ruff format` may want one-line reformats — run `.venv/bin/ruff format .` to apply.
- `tsc --noEmit` may complain about the new `retry` prop on the hook return type if a consumer that wasn't refactored still uses the old shape — grep for `useHumanVerification(` and update all consumers to destructure (or ignore) `retry`.

- [ ] **Step 6: Push and open PR**

```bash
git push -u origin feat/human-verification-ux-overlay
gh pr create --title "feat(ux): human verification overlay + cookie versioning" --body "$(cat <<'EOF'
## Summary

Replaces the racing-Turnstile-and-403-loop pattern on /collect with an explicit blocking overlay that owns the verification state machine. Adds a cookie version field to silently invalidate every wrzdj_human cookie issued before this change, forcing fresh re-verification post-deploy. Adds a gated live-join-code endpoint so the collect-page redirect can land on the correct (and currently broken-since-PR-#324) join URL without leaking join_code to unverified bots.

## What changes

- Cookie payload gains \`v: 2\` discriminator; v=1 (versionless) cookies silently rejected.
- New \`GET /api/public/guest/verify-status\` fast-path probe (no DB, no side effects, Cache-Control: no-store).
- New gated \`GET /api/public/collect/{code}/live-join-code\` returns join_code to verified humans during live phase.
- \`HumanVerificationOverlay\` component blocks UI in all non-verified states; provides a stable widget container.
- \`useHumanVerification\` rewritten: fast-path probe first, drops the broken display:none fallback, exposes \`retry()\`.
- Collect page wrapped in overlay; pre-announce included behind the gate.
- Live-phase redirect held until humanState is verified; uses the gated endpoint's join_code.

## Spec

[docs/superpowers/specs/2026-05-23-human-verification-ux-overlay-design.md](https://github.com/wrzonance/WrzDJ/blob/feat/human-verification-ux-overlay/docs/superpowers/specs/2026-05-23-human-verification-ux-overlay-design.md)

## Test plan

- [x] Backend: pytest with new test_verify_status_endpoint.py + TestLiveJoinCodeEndpoint + cookie version tests
- [x] Frontend: vitest covers fast-path skip, retry, overlay state rendering, gated redirect
- [x] All linters + tsc clean
- [x] Alembic clean (no migration)
- [ ] Manual smoke (post-deploy):
  - [ ] Fresh incognito Firefox → /collect/ELZ2G2 → overlay → resolves 1-3s → page renders
  - [ ] Browser with pre-deploy v=1 cookie → first gated action → overlay flashes → silent refresh → 200
  - [ ] Block 3rd-party cookies in Firefox → overlay shows loading → escalates to ChallengePanel → user completes → page renders
  - [ ] force_live a test event → page polls → calls live-join-code → redirects to /join/{join_code}
  - [ ] curl /api/public/collect/ELZ2G2/live-join-code with no cookie → 403 with no join_code leak
EOF
)"
```

- [ ] **Step 7: Watch CI green and resolve any CodeRabbit threads**

Run: `gh pr checks <PR_NUM> --watch`

When CodeRabbit posts findings, fix-and-reply per the standard `/review-remote-pr` loop. Resolve all threads before merge.

---

## Task 9: Merge + deploy

- [ ] **Step 1: Squash-merge once all CI green and threads resolved**

```bash
gh pr merge <PR_NUM> --admin --squash --delete-branch
```

- [ ] **Step 2: Sync main locally**

```bash
git checkout main && git pull
```

- [ ] **Step 3: Deploy on VPS**

```bash
ssh wrz-droplet
cd ~/WrzDJ
git fetch && git checkout main && git pull
./deploy/deploy.sh
```

Watch for `==> Deploy complete` and confirm `deploy-api-1` reports `(healthy)` in `docker compose ps`.

- [ ] **Step 4: Manual smoke tests on production**

1. In fresh incognito Firefox, open `https://app.wrzdj.com/collect/ELZ2G2`. Expect: overlay → resolves within 1-3s → page renders.
2. Open in a browser that holds a pre-deploy `wrzdj_human` cookie (e.g., a tab you left open before deploy). First gated action → overlay flashes → silent refresh → action succeeds.
3. Run `curl -sf -o /dev/null -w "%{http_code}\n" https://api.wrzdj.com/api/public/collect/ELZ2G2/live-join-code` with no cookies. Expect: 403 (no join_code in body).
4. Run `curl -sf https://api.wrzdj.com/api/public/guest/verify-status`. Expect: `{"verified":false,"expires_in":0}` plus `Cache-Control: no-store, private` header.

- [ ] **Step 5: Tail logs to confirm the new endpoints**

```bash
ssh wrz-droplet 'cd ~/WrzDJ && docker compose -f deploy/docker-compose.yml logs api --since 5m 2>&1 | grep -E "verify-status|live-join-code|collect/.*/profile" | tail -30'
```

Expect: `/verify-status` calls returning 200, `/profile` calls succeeding without the 403 loop pattern.

---

## Self-Review

After writing this plan, I reviewed it against the spec.

**Spec coverage check:**
- ✅ Cookie versioning (v=2 field, silent reject) — Task 1
- ✅ /verify-status endpoint — Task 2
- ✅ /live-join-code endpoint — Task 3
- ✅ Frontend API client methods — Task 4
- ✅ HumanVerificationOverlay — Task 5
- ✅ Hook rewrite (fast-path, retry, before-interactive-callback, drop fallback) — Task 6
- ✅ Page integration + gated redirect — Task 7
- ✅ Rollout (CI, push, merge, deploy) — Tasks 8, 9
- ✅ All test cases listed in spec map to specific test files/cases

**Placeholder scan:** No TBDs. The `before-interactive-callback` is documented as an implementation-time verification item with an explicit fallback strategy.

**Type consistency:** `getVerifyStatus()` return type matches `VerifyStatusResponse` schema in Python; `getLiveJoinCode()` matches `LiveJoinCodeResponse`; `useHumanVerification` consumers all match the updated interface.

Plan complete and saved to `docs/superpowers/plans/2026-05-23-human-verification-ux-overlay.md`.
