# LLM Cost / Quota Caps per DJ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let admins set a monthly token cap per DJ LLM connector; the gateway refuses calls that would push the current calendar month over the cap with a clear DJ-facing message.

**Architecture:** Add a nullable `monthly_token_cap` integer column to `LlmConnector` (None = unlimited). A direct aggregation query sums `tokens_in + tokens_out` from `llm_call_log` for the current calendar month per connector. The gateway runs a pre-flight check in `dispatch()`: if current month usage already meets/exceeds the cap, raise a new `QuotaCapReached` exception. Admins set caps via a new PATCH endpoint in `admin_llm.py`; the admin UI adds a cap input + usage-vs-cap progress bar per connector row.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2, Next.js 16 / React 19 (vanilla CSS), pytest, vitest.

**Why direct aggregation (not a rollup table):** At current volume (`llm_call_log` has a 30-365 day retention window, per-DJ DJ-initiated recommendation calls — low hundreds/month at most), a single indexed `SUM(...) WHERE created_at >= month_start GROUP BY connector_id` is correct and cheap. `llm_call_log.created_at` is already indexed. A materialized view or hourly cron rollup adds operational complexity (refresh scheduling, staleness windows, an extra table + migration) with no measurable benefit until call volume is orders of magnitude higher. Documented here and in the PR; revisit if usage telemetry shows the aggregation query becoming hot.

---

## File Structure

**Backend:**
- `server/app/models/llm_connector.py` — add `monthly_token_cap: Mapped[int | None]` column on `LlmConnector`.
- `server/alembic/versions/050_llm_connector_monthly_token_cap.py` — new migration (down_revision `049`).
- `server/app/services/llm/exceptions.py` — add `QuotaCapReached(LlmError)`.
- `server/app/services/llm/connector_storage.py` — add `current_month_token_usage(db, connector_id)` aggregation helper + `set_monthly_cap(connector, cap)` setter with validation.
- `server/app/services/llm/gateway.py` — add a pre-flight cap check in `dispatch()` before the primary attempt (and before any fallback attempt against a connector with a cap).
- `server/app/schemas/llm.py` — add `monthly_token_cap` to `ConnectorOut`; add `AdminConnectorCapPatch` request schema; add `current_month_tokens` to `AdminConnectorOut`.
- `server/app/api/admin_llm.py` — add `PATCH /connectors/{id}/cap` endpoint; populate `current_month_tokens` in the connectors listing.
- `server/app/api/events.py` — ensure `QuotaCapReached` from the LLM recommendation endpoint surfaces the DJ-facing 429 message instead of the generic 502.

**Frontend:**
- `dashboard/lib/api-types.generated.ts` — regenerated from backend OpenAPI (do not hand-edit).
- `dashboard/lib/api.ts` — add `setAdminLlmConnectorCap(id, cap)` method.
- `dashboard/app/admin/ai/page.tsx` — add cap input + usage-vs-cap progress bar to each per-DJ connector row.

**Tests:**
- `server/tests/test_llm_quota_cap.py` — new: aggregation helper, gateway pre-flight enforcement, cap setter validation.
- `server/tests/test_llm_api.py` — extend: admin cap PATCH endpoint (auth, validation, set/clear).
- `dashboard/app/admin/ai/__tests__/` or inline — cap UI rendering + progress bar (if an existing test harness for the page exists; otherwise add focused component-free logic test).

---

## Task 1: Add `QuotaCapReached` exception

**Files:**
- Modify: `server/app/services/llm/exceptions.py`
- Test: `server/tests/test_llm_quota_cap.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_llm_quota_cap.py`:

```python
"""Tests for per-DJ monthly token caps (issue #339)."""

from __future__ import annotations

from app.services.llm.exceptions import LlmError, QuotaCapReached


def test_quota_cap_reached_is_llm_error():
    exc = QuotaCapReached("cap reached")
    assert isinstance(exc, LlmError)
    assert str(exc) == "cap reached"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_llm_quota_cap.py -v`
Expected: FAIL — `ImportError: cannot import name 'QuotaCapReached'`

- [ ] **Step 3: Add the exception**

In `server/app/services/llm/exceptions.py`, after the `QuotaExceeded` class:

```python
class QuotaCapReached(LlmError):
    """The DJ's admin-set monthly token cap for this connector is reached.

    Distinct from :class:`QuotaExceeded` (a provider-side billing/quota error):
    this is a WrzDJ-internal pre-flight refusal raised *before* any provider
    call, so no tokens are spent. The DJ-facing message is fixed and contains
    no internal details — see the gateway pre-flight check.
    """
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_llm_quota_cap.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/services/llm/exceptions.py server/tests/test_llm_quota_cap.py
git commit -m "feat(llm): add QuotaCapReached exception for monthly token caps"
```

---

## Task 2: Add `monthly_token_cap` column + migration

**Files:**
- Modify: `server/app/models/llm_connector.py`
- Create: `server/alembic/versions/050_llm_connector_monthly_token_cap.py`
- Test: `server/tests/test_llm_quota_cap.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_llm_quota_cap.py`:

```python
import json

from app.models.llm_connector import LlmConnector
from app.models.user import User
from app.services.auth import get_password_hash


def _make_dj(db, username="capdj"):
    user = User(username=username, password_hash=get_password_hash("password123"), role="dj")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_connector(db, user, *, monthly_token_cap=None):
    row = LlmConnector(
        user_id=user.id,
        connector_type="openai_apikey",
        display_name="Cap connector",
        status="active",
        credentials=json.dumps({"api_key": "sk-fake-key"}),
        model_hint="gpt-5-mini",
        monthly_token_cap=monthly_token_cap,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_connector_defaults_to_no_cap(db):
    user = _make_dj(db)
    connector = _make_connector(db, user)
    assert connector.monthly_token_cap is None


def test_connector_stores_cap(db):
    user = _make_dj(db, username="capdj2")
    connector = _make_connector(db, user, monthly_token_cap=100_000)
    db.refresh(connector)
    assert connector.monthly_token_cap == 100_000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_llm_quota_cap.py -v`
Expected: FAIL — `TypeError: 'monthly_token_cap' is an invalid keyword argument for LlmConnector`

- [ ] **Step 3: Add the model column**

In `server/app/models/llm_connector.py`, inside `LlmConnector`, after the `last_health_check_status` column (before `__table_args__`):

```python
    # Admin-set monthly token cap (issue #339). NULL = unlimited. When set, the
    # gateway refuses dispatch once the current calendar month's summed
    # tokens_in + tokens_out for this connector meets or exceeds the cap. The
    # cap is admin-only (set via /api/admin/llm/connectors/{id}/cap) and is
    # checked PRE-FLIGHT only — editing it never disrupts an in-flight call.
    monthly_token_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

- [ ] **Step 4: Create the migration**

Create `server/alembic/versions/050_llm_connector_monthly_token_cap.py`:

```python
"""Add monthly_token_cap to llm_connectors (issue #339).

Revision ID: 050
Revises: 049
Create Date: 2026-05-28

Adds an admin-set per-DJ monthly token cap to ``llm_connectors``:

- ``monthly_token_cap`` (Integer, nullable) — NULL means unlimited. When set,
  the LLM gateway refuses dispatch once the current calendar month's summed
  ``tokens_in + tokens_out`` for the connector meets or exceeds this value.

Nullable with no server default so existing connectors stay unlimited.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "050"
down_revision: str | None = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_connectors",
        sa.Column("monthly_token_cap", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_connectors", "monthly_token_cap")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_llm_quota_cap.py -v`
Expected: PASS (SQLite test DB recreates schema from models)

- [ ] **Step 6: Verify alembic on isolated Postgres DB**

Run (isolated DB avoids the shared-DB drift from sibling worktrees):
```bash
DATABASE_URL="postgresql+psycopg://wrzdj:wrzdj@localhost:5432/wrzdj_issue339" .venv/bin/alembic upgrade head
DATABASE_URL="postgresql+psycopg://wrzdj:wrzdj@localhost:5432/wrzdj_issue339" .venv/bin/alembic check
```
Expected: `No new upgrade operations detected.`

If the isolated DB was already at head from a prior run, recreate it first:
```bash
docker exec wrzdj-db-1 psql -U wrzdj -d postgres -c "DROP DATABASE IF EXISTS wrzdj_issue339;" -c "CREATE DATABASE wrzdj_issue339;"
```

- [ ] **Step 7: Commit**

```bash
git add server/app/models/llm_connector.py server/alembic/versions/050_llm_connector_monthly_token_cap.py server/tests/test_llm_quota_cap.py
git commit -m "feat(llm): add monthly_token_cap column + migration 050"
```

---

## Task 3: Add current-month usage aggregation + cap setter helpers

**Files:**
- Modify: `server/app/services/llm/connector_storage.py`
- Test: `server/tests/test_llm_quota_cap.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_llm_quota_cap.py`:

```python
from datetime import timedelta

import pytest

from app.core.time import utcnow
from app.models.llm_connector import LlmCallLog
from app.services.llm.connector_storage import (
    current_month_token_usage,
    set_monthly_cap,
)


def _log(db, connector_id, *, tokens_in, tokens_out, when=None):
    row = LlmCallLog(
        connector_id=connector_id,
        purpose="test",
        status="ok",
        latency_ms=10,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    db.add(row)
    db.flush()
    if when is not None:
        row.created_at = when
    db.commit()
    return row


def test_current_month_usage_sums_in_and_out(db):
    user = _make_dj(db, username="usagedj")
    connector = _make_connector(db, user)
    _log(db, connector.id, tokens_in=100, tokens_out=50)
    _log(db, connector.id, tokens_in=10, tokens_out=5)
    assert current_month_token_usage(db, connector.id) == 165


def test_current_month_usage_excludes_prior_months(db):
    user = _make_dj(db, username="usagedj2")
    connector = _make_connector(db, user)
    # 40 days ago — previous month, must be excluded.
    _log(db, connector.id, tokens_in=1000, tokens_out=1000, when=utcnow() - timedelta(days=40))
    _log(db, connector.id, tokens_in=7, tokens_out=3)
    assert current_month_token_usage(db, connector.id) == 10


def test_current_month_usage_treats_null_tokens_as_zero(db):
    user = _make_dj(db, username="usagedj3")
    connector = _make_connector(db, user)
    _log(db, connector.id, tokens_in=None, tokens_out=None)
    _log(db, connector.id, tokens_in=5, tokens_out=None)
    assert current_month_token_usage(db, connector.id) == 5


def test_set_monthly_cap_accepts_positive_int(db):
    user = _make_dj(db, username="capset")
    connector = _make_connector(db, user)
    set_monthly_cap(connector, 50_000)
    assert connector.monthly_token_cap == 50_000


def test_set_monthly_cap_accepts_none_to_clear(db):
    user = _make_dj(db, username="capclear")
    connector = _make_connector(db, user, monthly_token_cap=10)
    set_monthly_cap(connector, None)
    assert connector.monthly_token_cap is None


def test_set_monthly_cap_rejects_negative(db):
    user = _make_dj(db, username="capneg")
    connector = _make_connector(db, user)
    with pytest.raises(ValueError):
        set_monthly_cap(connector, -1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_llm_quota_cap.py -v`
Expected: FAIL — `ImportError: cannot import name 'current_month_token_usage'`

- [ ] **Step 3: Implement the helpers**

In `server/app/services/llm/connector_storage.py`, add a module-level helper for the month boundary and the two functions. Add near the other aggregation helpers (after `get_usage_stats`):

```python
def _calendar_month_start() -> "datetime":
    """First instant (UTC, naive) of the current calendar month."""
    from app.core.time import utcnow

    now = utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def current_month_token_usage(db: Session, connector_id: int) -> int:
    """Sum tokens_in + tokens_out for ``connector_id`` in the current month.

    Direct aggregation against the indexed ``llm_call_log.created_at`` column.
    NULL token counts are coalesced to 0. Returns 0 when there are no rows.
    Used by the gateway pre-flight cap check + the admin usage-vs-cap display.
    """
    month_start = _calendar_month_start()
    total = db.execute(
        select(
            func.coalesce(func.sum(LlmCallLog.tokens_in), 0)
            + func.coalesce(func.sum(LlmCallLog.tokens_out), 0)
        ).where(
            LlmCallLog.connector_id == connector_id,
            LlmCallLog.created_at >= month_start,
        )
    ).scalar_one()
    return int(total or 0)


def set_monthly_cap(connector: LlmConnector, cap: int | None) -> LlmConnector:
    """Set (or clear) the connector's monthly token cap. Caller commits.

    ``cap=None`` clears the cap (unlimited). A non-None cap must be a
    non-negative integer; negative values are rejected with ``ValueError``
    (→ HTTP 400 at the API boundary).
    """
    if cap is not None and cap < 0:
        raise ValueError("monthly_token_cap must be a non-negative integer or null")
    connector.monthly_token_cap = cap
    return connector
```

Add `datetime` to the typing import context — the `_calendar_month_start` return annotation uses a string forward-ref `"datetime"`, but for clarity add `from datetime import datetime` at the top of the module if not already imported. Check the existing imports first; if `datetime` is not imported, add it. Then change the annotation to `-> datetime:` (drop the quotes).

Add both new names to the `__all__` list:

```python
    "current_month_token_usage",
    "set_monthly_cap",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_llm_quota_cap.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/services/llm/connector_storage.py server/tests/test_llm_quota_cap.py
git commit -m "feat(llm): add current-month usage aggregation + cap setter"
```

---

## Task 4: Gateway pre-flight cap enforcement

**Files:**
- Modify: `server/app/services/llm/gateway.py`
- Test: `server/tests/test_llm_quota_cap.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_llm_quota_cap.py`:

```python
from unittest.mock import AsyncMock, patch

from app.services.llm.adapters.openai_apikey import OpenAIApiKeyAdapter
from app.services.llm.base import ChatRequest, ChatResponse, Message, TokenUsage
from app.services.llm.exceptions import QuotaCapReached
from app.services.llm.gateway import Gateway


def _req() -> ChatRequest:
    return ChatRequest(messages=[Message(role="user", content="hi")])


@pytest.mark.asyncio
async def test_dispatch_allows_when_under_cap(db):
    user = _make_dj(db, username="undercap")
    connector = _make_connector(db, user, monthly_token_cap=1_000)
    _log(db, connector.id, tokens_in=100, tokens_out=100)  # 200 used, under 1000

    fake = ChatResponse(text="ok", tool_calls=[], stop_reason="end_turn",
                         usage=TokenUsage(prompt=5, completion=2))
    with patch.object(OpenAIApiKeyAdapter, "chat", new=AsyncMock(return_value=fake)):
        resp = await Gateway.dispatch(db, user, _req(), purpose="test")
    assert resp.text == "ok"


@pytest.mark.asyncio
async def test_dispatch_refuses_when_cap_reached(db):
    user = _make_dj(db, username="atcap")
    connector = _make_connector(db, user, monthly_token_cap=200)
    _log(db, connector.id, tokens_in=150, tokens_out=50)  # 200 used, == cap

    # The adapter must NOT be called — refusal is pre-flight.
    chat_mock = AsyncMock()
    with patch.object(OpenAIApiKeyAdapter, "chat", new=chat_mock):
        with pytest.raises(QuotaCapReached):
            await Gateway.dispatch(db, user, _req(), purpose="test")
    chat_mock.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_unlimited_when_cap_none(db):
    user = _make_dj(db, username="nolimit")
    connector = _make_connector(db, user, monthly_token_cap=None)
    _log(db, connector.id, tokens_in=10_000, tokens_out=10_000)

    fake = ChatResponse(text="ok", tool_calls=[], stop_reason="end_turn",
                        usage=TokenUsage(prompt=1, completion=1))
    with patch.object(OpenAIApiKeyAdapter, "chat", new=AsyncMock(return_value=fake)):
        resp = await Gateway.dispatch(db, user, _req(), purpose="test")
    assert resp.text == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_llm_quota_cap.py -k cap -v`
Expected: FAIL — `test_dispatch_refuses_when_cap_reached` fails because the adapter is called and no `QuotaCapReached` is raised.

- [ ] **Step 3: Implement the pre-flight check**

In `server/app/services/llm/gateway.py`:

Add the import for the helper + exception. Update the `from app.services.llm.connector_storage import ...` line:

```python
from app.services.llm.connector_storage import (
    audit_event,
    current_month_token_usage,
    log_call,
)
```

Add `QuotaCapReached` to the exceptions import block:

```python
from app.services.llm.exceptions import (
    AuthInvalid,
    LlmError,
    NoLlmConfigured,
    ProviderUnavailable,
    QuotaCapReached,
    QuotaExceeded,
    RateLimited,
    ToolTranslationError,
)
```

Add a module-level helper after `_fallback_trigger`:

```python
def _enforce_monthly_cap(db: Session, connector: LlmConnector) -> None:
    """Pre-flight: refuse dispatch when the connector's monthly cap is reached.

    No-op when the connector has no cap (``monthly_token_cap is None``).
    Compares the current calendar month's summed token usage against the cap;
    refuses when usage already meets or exceeds it. Raised BEFORE any provider
    call, so no tokens are spent and editing the cap never disrupts an
    already-dispatched (in-flight) call.

    The error message is fixed and leaks no internals (usage totals, cap value,
    connector id) — see issue #339 security note.
    """
    cap = connector.monthly_token_cap
    if cap is None:
        return
    used = current_month_token_usage(db, connector.id)
    if used >= cap:
        raise QuotaCapReached(
            "Your monthly token cap is reached. Contact your admin to raise it."
        )
```

In `Gateway.dispatch`, add the pre-flight check immediately after `primary = _resolve_connector(...)` / `actor_id = ...` and before "Attempt 1":

```python
        primary = _resolve_connector(db, actor)
        actor_id = actor.id if actor else _system_actor_id(db, primary)

        # Pre-flight: refuse if the resolved connector's monthly cap is reached
        # (issue #339). Raised before any provider call — no tokens spent.
        _enforce_monthly_cap(db, primary)
```

Also enforce the cap on the fallback connector before the fallback attempt. In the fallback branch, after `fallback = _resolve_org_default(db)` and the `if fallback is None or fallback.id == primary.id: raise` guard, before the `audit_event(...)` write, add:

```python
            # The fallback connector may itself be capped — refuse rather than
            # silently spending another DJ's budget.
            _enforce_monthly_cap(db, fallback)
```

`QuotaCapReached` is a subclass of `LlmError` but is NOT in `_FALLBACK_TRIGGERS`, so `_fallback_trigger()` returns `None` for it and the primary-connector cap refusal short-circuits to `raise` (no fallback) — which is correct: a cap is not a transient/credential error.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_llm_quota_cap.py -v`
Expected: PASS (all cap tests)

Run the full gateway suite to confirm no regression:
Run: `.venv/bin/pytest tests/test_llm_gateway.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/services/llm/gateway.py server/tests/test_llm_quota_cap.py
git commit -m "feat(llm): enforce monthly token cap pre-flight in gateway dispatch"
```

---

## Task 5: Expose cap in schemas + admin connectors listing

**Files:**
- Modify: `server/app/schemas/llm.py`
- Modify: `server/app/api/admin_llm.py`
- Test: `server/tests/test_llm_api.py`

- [ ] **Step 1: Write the failing test**

Add to `server/tests/test_llm_api.py` (find the admin connectors-listing test area; add a new test). First inspect the file for an existing admin connector + admin_headers fixture pattern, then add:

```python
def test_admin_connectors_listing_includes_cap_and_usage(client, db, admin_headers, dj_user):
    # Create a connector for a DJ with a cap, and log some usage this month.
    import json as _json

    from app.models.llm_connector import LlmCallLog, LlmConnector

    connector = LlmConnector(
        user_id=dj_user.id,
        connector_type="openai_apikey",
        display_name="Capped",
        status="active",
        credentials=_json.dumps({"api_key": "sk-fake-key"}),
        monthly_token_cap=1000,
    )
    db.add(connector)
    db.commit()
    db.refresh(connector)
    db.add(LlmCallLog(connector_id=connector.id, purpose="test", status="ok",
                      latency_ms=5, tokens_in=120, tokens_out=80))
    db.commit()

    resp = client.get("/api/admin/llm/connectors", headers=admin_headers)
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["id"] == connector.id)
    assert row["monthly_token_cap"] == 1000
    assert row["current_month_tokens"] == 200
```

If `test_llm_api.py` has no `dj_user` fixture, create the DJ inline (mirror the local connector-creation helpers already used in that file).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_llm_api.py -k cap_and_usage -v`
Expected: FAIL — `KeyError: 'monthly_token_cap'` or `'current_month_tokens'`

- [ ] **Step 3: Update schemas**

In `server/app/schemas/llm.py`:

Add to `ConnectorOut` (after `last_health_check_status`):

```python
    # Admin-set monthly token cap (issue #339). None = unlimited.
    monthly_token_cap: int | None = None
```

Add to `AdminConnectorOut` (after `dj_username`):

```python
    # Current calendar-month token usage (tokens_in + tokens_out), so the admin
    # UI can render a usage-vs-cap progress bar without a second round-trip.
    current_month_tokens: int = 0
```

Add a new request schema near `AdminPolicyPatch`:

```python
class AdminConnectorCapPatch(BaseModel):
    """Admin set/clear a connector's monthly token cap (issue #339).

    ``monthly_token_cap = null`` clears the cap (unlimited). A non-null value
    must be a non-negative integer; ``0`` means "no further calls this month".
    """

    monthly_token_cap: int | None = Field(default=None, ge=0, le=1_000_000_000)
```

- [ ] **Step 4: Populate `current_month_tokens` in the listing**

In `server/app/api/admin_llm.py`:

Import the helper:

```python
from app.services.llm.connector_storage import (
    AUDIT_POLICY_CHANGED,
    AUDIT_REVOKED_BY_ADMIN,
    audit_event,
    current_month_token_usage,
    get_connector,
    get_usage_stats,
    get_user_label,
    list_all_connectors,
    revoke_connector,
)
```

Update `_connector_to_admin_out` to accept and inject `current_month_tokens`:

```python
def _connector_to_admin_out(
    row: LlmConnector, dj_username: str, current_month_tokens: int = 0
) -> AdminConnectorOut:
    return AdminConnectorOut.model_validate(
        {
            **{c.name: getattr(row, c.name) for c in LlmConnector.__table__.columns},
            "dj_username": dj_username,
            "current_month_tokens": current_month_tokens,
        }
    )
```

In `list_connectors_admin`, compute usage per row:

```python
    return [
        _connector_to_admin_out(
            r,
            usernames.get(r.user_id) or f"user#{r.user_id}",
            current_month_token_usage(db, r.id),
        )
        for r in rows
    ]
```

Update the two other `_connector_to_admin_out(...)` call sites in `revoke_connector_admin` (and the new cap endpoint in Task 6) to pass `current_month_token_usage(db, row.id)`.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_llm_api.py -k cap_and_usage -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add server/app/schemas/llm.py server/app/api/admin_llm.py server/tests/test_llm_api.py
git commit -m "feat(llm): expose monthly cap + current-month usage in admin listing"
```

---

## Task 6: Admin PATCH endpoint to set/clear a connector cap

**Files:**
- Modify: `server/app/api/admin_llm.py`
- Test: `server/tests/test_llm_api.py`

- [ ] **Step 1: Write the failing test**

Add to `server/tests/test_llm_api.py`:

```python
def test_admin_set_connector_cap(client, db, admin_headers, dj_user):
    import json as _json

    from app.models.llm_connector import LlmConnector

    connector = LlmConnector(
        user_id=dj_user.id, connector_type="openai_apikey", display_name="C",
        status="active", credentials=_json.dumps({"api_key": "sk-fake-key"}),
    )
    db.add(connector)
    db.commit()
    db.refresh(connector)

    resp = client.patch(
        f"/api/admin/llm/connectors/{connector.id}/cap",
        headers=admin_headers,
        json={"monthly_token_cap": 50000},
    )
    assert resp.status_code == 200
    assert resp.json()["monthly_token_cap"] == 50000

    # Clear it.
    resp = client.patch(
        f"/api/admin/llm/connectors/{connector.id}/cap",
        headers=admin_headers,
        json={"monthly_token_cap": None},
    )
    assert resp.status_code == 200
    assert resp.json()["monthly_token_cap"] is None


def test_admin_set_cap_rejects_negative(client, db, admin_headers, dj_user):
    import json as _json

    from app.models.llm_connector import LlmConnector

    connector = LlmConnector(
        user_id=dj_user.id, connector_type="openai_apikey", display_name="C2",
        status="active", credentials=_json.dumps({"api_key": "sk-fake-key"}),
    )
    db.add(connector)
    db.commit()
    db.refresh(connector)

    resp = client.patch(
        f"/api/admin/llm/connectors/{connector.id}/cap",
        headers=admin_headers,
        json={"monthly_token_cap": -5},
    )
    assert resp.status_code == 422  # Pydantic ge=0 rejection


def test_admin_set_cap_404_for_missing_connector(client, admin_headers):
    resp = client.patch(
        "/api/admin/llm/connectors/999999/cap",
        headers=admin_headers,
        json={"monthly_token_cap": 100},
    )
    assert resp.status_code == 404


def test_set_cap_requires_admin(client, db, auth_headers, test_user):
    # A non-admin (plain DJ) must be rejected.
    import json as _json

    from app.models.llm_connector import LlmConnector

    connector = LlmConnector(
        user_id=test_user.id, connector_type="openai_apikey", display_name="C3",
        status="active", credentials=_json.dumps({"api_key": "sk-fake-key"}),
    )
    db.add(connector)
    db.commit()
    db.refresh(connector)

    resp = client.patch(
        f"/api/admin/llm/connectors/{connector.id}/cap",
        headers=auth_headers,
        json={"monthly_token_cap": 100},
    )
    assert resp.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_llm_api.py -k cap -v`
Expected: FAIL — 404/405 (endpoint not yet defined)

- [ ] **Step 3: Add the endpoint**

In `server/app/api/admin_llm.py`:

Add `AdminConnectorCapPatch` to the schema imports and `set_monthly_cap` + audit constant to the storage imports. Add a new audit constant usage — reuse `AUDIT_POLICY_CHANGED` for cap changes (it is the closest existing lifecycle event and avoids a model change), OR add a dedicated `AUDIT_CAP_CHANGED` if preferred. Use `AUDIT_POLICY_CHANGED` to avoid touching the model's audit constants and migrations.

Imports:

```python
from app.schemas.llm import (
    AdminAuditOut,
    AdminConnectorCapPatch,
    AdminConnectorOut,
    AdminPolicyOut,
    AdminPolicyPatch,
    AdminUsageOut,
    AuditEventRow,
    UsageRow,
)
from app.services.llm.connector_storage import (
    AUDIT_POLICY_CHANGED,
    AUDIT_REVOKED_BY_ADMIN,
    audit_event,
    current_month_token_usage,
    get_connector,
    get_usage_stats,
    get_user_label,
    list_all_connectors,
    revoke_connector,
    set_monthly_cap,
)
```

Add the endpoint (place it after `revoke_connector_admin`):

```python
@router.patch("/connectors/{connector_id}/cap", response_model=AdminConnectorOut)
@limiter.limit("30/minute")
def set_connector_cap_admin(
    request: FastAPIRequest,
    connector_id: int,
    payload: AdminConnectorCapPatch,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminConnectorOut:
    """Set or clear a connector's monthly token cap (admin-only, issue #339).

    ``monthly_token_cap = null`` clears the cap (unlimited). The change is
    pre-flight only: an in-flight gateway call already past its cap check is
    unaffected. Pydantic enforces the non-negative bound (``ge=0``).
    """
    row = get_connector(db, connector_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Connector not found")

    try:
        set_monthly_cap(row, payload.monthly_token_cap)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_event(
        db,
        actor_user_id=admin.id,
        target_connector_id=row.id,
        event_type=AUDIT_POLICY_CHANGED,
    )
    db.commit()
    db.refresh(row)
    return _connector_to_admin_out(
        row, get_user_label(db, row.user_id), current_month_token_usage(db, row.id)
    )
```

Also update `revoke_connector_admin`'s final return to pass usage:

```python
    return _connector_to_admin_out(
        row, get_user_label(db, row.user_id), current_month_token_usage(db, row.id)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_llm_api.py -k cap -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/api/admin_llm.py server/tests/test_llm_api.py
git commit -m "feat(llm): admin endpoint to set/clear per-connector monthly cap"
```

---

## Task 7: Surface `QuotaCapReached` as a clear DJ-facing error

**Files:**
- Modify: `server/app/api/events.py:923-988` (the `/recommendations/llm` endpoint)
- Test: `server/tests/test_llm_recommendation_via_gateway.py` (or `test_llm_quota_cap.py`)

- [ ] **Step 1: Write the failing test**

Inspect `server/tests/test_llm_recommendation_via_gateway.py` for the existing event + DJ + connector fixture pattern and how `/recommendations/llm` is exercised. Add a test that pre-fills usage at/over a cap and asserts a 429 with the DJ-facing message:

```python
def test_llm_recommendation_returns_429_when_cap_reached(client, db, ...):
    # ... set up event owned by a DJ with a capped, active connector and
    # a connected music service (tidal/beatport token), then log usage >= cap.
    # POST /api/events/{code}/recommendations/llm with a prompt.
    assert resp.status_code == 429
    assert "monthly token cap is reached" in resp.json()["detail"].lower()
```

Model this test on the existing setup in `test_llm_recommendation_via_gateway.py`. If that file's fixtures are too heavy to reuse cleanly, instead unit-test the mapping by patching `generate_recommendations_from_llm` to raise `QuotaCapReached` and asserting the endpoint returns 429 with the message.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_llm_recommendation_via_gateway.py -k cap -v`
Expected: FAIL — endpoint returns 502 (generic) instead of 429 with the cap message.

- [ ] **Step 3: Handle `QuotaCapReached` before the generic catch**

In `server/app/api/events.py`, in `get_llm_recommendations`, change the try/except around `generate_recommendations_from_llm` to catch the cap error first:

```python
    from app.services.llm.exceptions import QuotaCapReached

    try:
        result = await generate_recommendations_from_llm(db, user, event, prompt_request.prompt)
    except QuotaCapReached as exc:
        # DJ-facing message only — no internal usage/cap details leaked.
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception:
        import logging

        logging.getLogger(__name__).exception("LLM recommendation failed")
        raise HTTPException(
            status_code=502,
            detail="LLM service error. Try again or use algorithmic recommendations.",
        )
```

Place the `from app.services.llm.exceptions import QuotaCapReached` import with the other local imports at the top of the function (next to the existing `from app.services.recommendation...` imports).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_llm_recommendation_via_gateway.py -k cap -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/api/events.py server/tests/test_llm_recommendation_via_gateway.py
git commit -m "feat(llm): surface QuotaCapReached as 429 with DJ-facing message"
```

---

## Task 8: Regenerate frontend types + add api.ts method

**Files:**
- Modify: `dashboard/lib/api-types.generated.ts` (regenerated)
- Modify: `dashboard/lib/api-types.ts` (add `LlmAdminConnectorCapPatch` alias)
- Modify: `dashboard/lib/api.ts`
- Test: `dashboard/lib/__tests__/api.test.ts`

- [ ] **Step 1: Regenerate types from backend OpenAPI**

Run from `dashboard/`:
```bash
npm run types:export
npm run types:generate
```
Verify `AdminConnectorCapPatch` and `current_month_tokens` / `monthly_token_cap` appear in `dashboard/lib/api-types.generated.ts`.

- [ ] **Step 2: Add type alias**

In `dashboard/lib/api-types.ts`, near the other LLM aliases:

```typescript
export type LlmAdminConnectorCapPatch = Schemas['AdminConnectorCapPatch'];
```

- [ ] **Step 3: Write the failing test**

In `dashboard/lib/__tests__/api.test.ts`, add a test mirroring the existing admin-LLM method tests (find one like `revokeAdminLlmConnector`):

```typescript
it('setAdminLlmConnectorCap PATCHes the cap endpoint', async () => {
  const connector = { id: 7, monthly_token_cap: 5000 };
  mockFetchOnce(connector);
  const result = await api.setAdminLlmConnectorCap(7, 5000);
  expect(lastFetchUrl()).toContain('/api/admin/llm/connectors/7/cap');
  expect(lastFetchInit().method).toBe('PATCH');
  expect(JSON.parse(lastFetchInit().body as string)).toEqual({ monthly_token_cap: 5000 });
  expect(result).toEqual(connector);
});
```

Adjust `mockFetchOnce`/`lastFetchUrl`/`lastFetchInit` to match the helpers already used in that test file.

- [ ] **Step 4: Run test to verify it fails**

Run from `dashboard/`: `npm test -- --run api.test`
Expected: FAIL — `api.setAdminLlmConnectorCap is not a function`

- [ ] **Step 5: Add the method**

In `dashboard/lib/api.ts`, in the "Admin LLM policy + oversight" section (after `getAdminLlmUsage`):

```typescript
  async setAdminLlmConnectorCap(
    id: number,
    monthlyTokenCap: number | null,
  ): Promise<LlmAdminConnector> {
    return this.fetch(`/api/admin/llm/connectors/${id}/cap`, {
      method: 'PATCH',
      body: JSON.stringify({ monthly_token_cap: monthlyTokenCap }),
    });
  }
```

Add `LlmAdminConnectorCapPatch` to the imports if you reference it; the method signature above uses primitives, so an import is optional.

- [ ] **Step 6: Run test to verify it passes**

Run from `dashboard/`: `npm test -- --run api.test`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add dashboard/lib/api-types.generated.ts dashboard/lib/api-types.ts dashboard/lib/api.ts dashboard/lib/__tests__/api.test.ts
git commit -m "feat(ai-ui): add setAdminLlmConnectorCap api client method + types"
```

---

## Task 9: Admin UI — cap input + usage-vs-cap progress bar

**Files:**
- Modify: `dashboard/app/admin/ai/page.tsx`
- Test: extend the page's test if one exists, otherwise a focused logic test for the percent helper.

- [ ] **Step 1: Add a cap-percent helper + extract a small pure function (testable)**

In `dashboard/app/admin/ai/page.tsx`, add near the top-level helpers (e.g. after `formatTimestamp`):

```typescript
// Percent of the monthly cap consumed. Returns null when there is no cap
// (unlimited) so the UI can render "Unlimited" instead of a bar. Clamps to
// 0–100 so an over-cap connector (possible: cap lowered mid-month) shows full.
function capPercent(used: number, cap: number | null | undefined): number | null {
  if (cap == null) return null;
  if (cap === 0) return 100;
  return Math.min(100, Math.max(0, Math.round((used / cap) * 100)));
}
```

- [ ] **Step 2: Add a "Monthly cap" column to the connectors table**

Add a `<PlainHeader label="Monthly cap" />` to the table head (after "Result", before "Actions").

In each connector `<tr>`, add a cell that shows the current usage, an editable cap input, and a progress bar:

```tsx
                    <td style={{ padding: '0.5rem', minWidth: '180px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <input
                          type="number"
                          className="input"
                          style={{ width: '110px' }}
                          min={0}
                          placeholder="∞"
                          defaultValue={c.monthly_token_cap ?? ''}
                          onBlur={(e) => handleCapBlur(c, e.target.value)}
                          aria-label={`Monthly token cap for ${c.dj_username} ${c.display_name}`}
                        />
                      </div>
                      <div style={{ marginTop: '0.35rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                        {c.monthly_token_cap == null
                          ? `${c.current_month_tokens.toLocaleString()} this month · unlimited`
                          : `${c.current_month_tokens.toLocaleString()} / ${c.monthly_token_cap.toLocaleString()}`}
                      </div>
                      {c.monthly_token_cap != null && (
                        <div
                          aria-hidden
                          style={{
                            marginTop: '0.25rem',
                            height: '6px',
                            borderRadius: '9999px',
                            background: 'var(--border-color)',
                            overflow: 'hidden',
                          }}
                        >
                          <div
                            style={{
                              width: `${capPercent(c.current_month_tokens, c.monthly_token_cap) ?? 0}%`,
                              height: '100%',
                              background:
                                (capPercent(c.current_month_tokens, c.monthly_token_cap) ?? 0) >= 100
                                  ? 'var(--color-danger)'
                                  : (capPercent(c.current_month_tokens, c.monthly_token_cap) ?? 0) >= 80
                                    ? 'var(--color-warning, #c08418)'
                                    : 'var(--color-success)',
                            }}
                          />
                        </div>
                      )}
                    </td>
```

- [ ] **Step 3: Add the `handleCapBlur` handler**

Add inside the component (near `handleRevoke`):

```typescript
  const handleCapBlur = async (connector: LlmAdminConnector, raw: string) => {
    const trimmed = raw.trim();
    // Empty input clears the cap (unlimited).
    let next: number | null;
    if (trimmed === '') {
      next = null;
    } else {
      const parsed = parseInt(trimmed, 10);
      if (Number.isNaN(parsed) || parsed < 0) {
        setError('Monthly cap must be a non-negative whole number.');
        return;
      }
      next = parsed;
    }
    // No-op when unchanged.
    if (next === (connector.monthly_token_cap ?? null)) return;
    try {
      const updated = await api.setAdminLlmConnectorCap(connector.id, next);
      setConnectors((prev) => prev.map((c) => (c.id === connector.id ? updated : c)));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update cap');
    }
  };
```

- [ ] **Step 4: Type check + lint + tests**

Run from `dashboard/`:
```bash
npx tsc --noEmit
npm run lint
npm test -- --run
git checkout next-env.d.ts 2>/dev/null || true
```
Expected: all green. Fix any type errors (e.g. `current_month_tokens` should be a `number` on `LlmAdminConnector` from the regenerated types).

- [ ] **Step 5: Commit**

```bash
git add dashboard/app/admin/ai/page.tsx
git commit -m "feat(ai-ui): admin cap input + usage-vs-cap progress bar per connector"
```

---

## Task 10: Full local CI + finalize

- [ ] **Step 1: Backend CI**

From `server/`:
```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/bandit -r app -c pyproject.toml -q
.venv/bin/pytest --tb=short -q
```
Fix anything red. Run `.venv/bin/ruff format .` then `.venv/bin/ruff check --fix .` if needed.

- [ ] **Step 2: Alembic on isolated DB**

```bash
docker exec wrzdj-db-1 psql -U wrzdj -d postgres -c "DROP DATABASE IF EXISTS wrzdj_issue339;" -c "CREATE DATABASE wrzdj_issue339;"
DATABASE_URL="postgresql+psycopg://wrzdj:wrzdj@localhost:5432/wrzdj_issue339" .venv/bin/alembic upgrade head
DATABASE_URL="postgresql+psycopg://wrzdj:wrzdj@localhost:5432/wrzdj_issue339" .venv/bin/alembic check
```
Expected: `No new upgrade operations detected.`

- [ ] **Step 3: Frontend CI**

From `dashboard/`:
```bash
npm run lint
npx tsc --noEmit
npm test -- --run
git checkout next-env.d.ts 2>/dev/null || true
```

- [ ] **Step 4: Push + PR**

Use `superpowers:finishing-a-development-branch` option 2. Create the PR with `gh pr create --base epic/ai-engine`. PR body MUST include `Closes #339`, a `## Design decisions` section (direct-aggregation rationale, pre-flight-only enforcement, reuse of `AUDIT_POLICY_CHANGED`, 429 mapping), and a note that it targets `epic/ai-engine`.

---

## Self-Review Notes

- **Spec coverage:** column (T2), aggregation (T3), pre-flight `QuotaCapReached` (T4), admin set/edit endpoint (T6), DJ-facing message (T4 msg + T7 mapping), admin UI cap input + progress bar (T9). Acceptance: cap enforced (T4), clear DJ error (T4/T7), admin edits without disrupting in-flight calls (pre-flight-only, documented T4/T6). ✓
- **Type consistency:** `current_month_token_usage(db, connector_id)`, `set_monthly_cap(connector, cap)`, `monthly_token_cap`, `current_month_tokens`, `setAdminLlmConnectorCap(id, cap)`, `capPercent(used, cap)`, `handleCapBlur(connector, raw)` used consistently across tasks. ✓
- **Security:** Pydantic `ge=0` + service `ValueError` guard; admin-only via `get_current_admin`; fixed DJ-facing message leaks no internals; parameterized SQLAlchemy queries only. ✓
