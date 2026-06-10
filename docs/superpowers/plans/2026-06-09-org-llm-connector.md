# Org LLM Connector + Admin AI Policy Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an org-scoped LLM connector (house-billed fallback), rescope `llm_enabled` to gate only that fallback, and remove the legacy Anthropic env-var admin surface.

**Architecture:** Org connectors live in the existing `llm_connectors` table with a new `scope` column (`'user'`/`'org'`) and nullable `user_id` (CHECK: org ⇔ NULL user). The gateway's per-DJ resolution chain filters to `scope='user'`; the org-default fallback requires `scope='org'` AND `SystemSettings.llm_enabled`. Audit rows allow NULL actor for system-context calls. Admin CRUD for the org connector reuses the existing `connector_storage` + `run_health_check` plumbing.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic (backend), Next.js/React + vitest (frontend), pytest (backend tests).

**Spec:** `docs/superpowers/specs/2026-06-09-admin-ai-policy-design.md` (approved). One correction discovered during planning: the DJ-side connector UI is `dashboard/components/AiProvidersSection.tsx` rendered on `/account` — not a `/settings/ai` page. Section 5 of the spec applies to that component.

**Working directory:** `/home/adam/github/WrzDJ-worktrees/org-llm` (branch `feat/org-llm-connector`). The main checkout at `/home/adam/github/WrzDJ` is running the live testing instance — do not run servers or migrations against its database (port 5432).

---

### Task 0: Worktree setup

**Files:** none (environment only)

- [ ] **Step 1: Copy `.env` and link `node_modules`**

```bash
cd /home/adam/github/WrzDJ-worktrees/org-llm
cp /home/adam/github/WrzDJ/.env .env
ln -sfn /home/adam/github/WrzDJ/dashboard/node_modules dashboard/node_modules
```

(The symlinked `node_modules` is fine for vitest/tsc; do NOT run `next dev` from this worktree — Turbopack breaks on the symlink.)

- [ ] **Step 2: Verify the main venv works from the worktree**

There is no venv in the worktree; use the main checkout's. All backend commands in this plan use:

```bash
export VENV=/home/adam/github/WrzDJ/server/.venv
cd /home/adam/github/WrzDJ-worktrees/org-llm/server
$VENV/bin/pytest tests/test_llm_gateway.py -q
```

Expected: tests collect and pass (pytest `pythonpath` config resolves `app` from the worktree's cwd).

- [ ] **Step 3: Verify frontend tooling**

```bash
cd /home/adam/github/WrzDJ-worktrees/org-llm/dashboard
npx vitest run lib/__tests__/theme-vars.test.ts --reporter=dot
```

Expected: PASS.

---

### Task 1: Model changes — scope column, nullable user_id, nullable audit actor, drop llm_model

**Files:**
- Modify: `server/app/models/llm_connector.py`
- Modify: `server/app/models/system_settings.py`
- Modify: `server/app/services/system_settings.py`
- Modify: `server/app/schemas/system_settings.py`

- [ ] **Step 1: Add scope constants + column to `LlmConnector`**

In `server/app/models/llm_connector.py`, after the `STATUS_*` constants block (line ~56), add:

```python
# Connector scope — 'user' rows belong to a DJ; 'org' rows belong to the
# organization itself (house-billed fallback). Org rows have user_id NULL,
# enforced by ck_llm_connectors_org_scope_no_user below.
SCOPE_USER = "user"
SCOPE_ORG = "org"
```

Change the `user_id` column (lines 116-118) to nullable:

```python
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True
    )
```

After `connector_type` (line 119), add the scope column:

```python
    scope: Mapped[str] = mapped_column(
        String(10), nullable=False, default=SCOPE_USER, server_default=text("'user'")
    )
```

In `__table_args__`, add (alongside the existing cap CheckConstraint):

```python
        # Org rows must have no owner; user rows must have one.
        CheckConstraint(
            "(scope = 'org') = (user_id IS NULL)",
            name="ck_llm_connectors_org_scope_no_user",
        ),
```

- [ ] **Step 2: Make `LlmAuditEvent.actor_user_id` nullable**

In the same file (line 222):

```python
    # NULL actor = system-context call (no DJ actor); see gateway dispatch.
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )
```

- [ ] **Step 3: Drop `llm_model` from `SystemSettings`**

In `server/app/models/system_settings.py`, delete the line:

```python
    llm_model: Mapped[str] = mapped_column(String(100), default="claude-haiku-4-5-20251001")
```

Update the comment above `llm_enabled` to document the new semantics:

```python
    # LLM / AI settings.
    # llm_enabled gates ONLY the org-connector fallback (connector-less DJs and
    # system-context calls). DJs with their own active connector are never
    # blocked by this flag. See docs/superpowers/specs/2026-06-09-admin-ai-policy-design.md.
    llm_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
```

- [ ] **Step 4: Remove `llm_model` from the settings service and schemas**

In `server/app/services/system_settings.py`:
- delete `llm_model="claude-haiku-4-5-20251001",` from the lazy-create defaults (line 25)
- delete the `llm_model: str | None = None,` parameter (line 48)
- delete the `if llm_model is not None: settings.llm_model = llm_model` block (lines 73-74)

In `server/app/schemas/system_settings.py`: remove the `llm_model: str` field (line 15) and `llm_model: str | None = None` (line 28).

- [ ] **Step 5: Find remaining references and fix them**

```bash
cd /home/adam/github/WrzDJ-worktrees/org-llm/server
grep -rn "settings.llm_model\|llm_model=" app/ --include="*.py" | grep -v track_vibe | grep -v "llm_model: str"
```

Expected hits to fix in later tasks (do NOT fix yet, just confirm the list): `app/api/admin.py` (Task 7), `app/api/events.py:1007` (Task 7). `TrackVibe.llm_model` and `schemas/recommendation.py` `llm_model` are response/telemetry fields, NOT the system setting — leave untouched.

- [ ] **Step 6: Run model-touching tests — expect failures only where settings construct llm_model**

```bash
$VENV/bin/pytest tests/test_admin_api.py tests/test_llm_gateway.py -q 2>&1 | tail -5
```

Expected: failures referencing `llm_model` (admin AI settings tests) — these are fixed in Task 7. If `test_llm_gateway.py` fails for other reasons, stop and investigate.

- [ ] **Step 7: Commit**

```bash
cd /home/adam/github/WrzDJ-worktrees/org-llm
git add server/app/models/ server/app/services/system_settings.py server/app/schemas/system_settings.py
git commit -m "feat(llm): scope column on connectors, nullable audit actor, drop llm_model setting"
```

(Known-red tests are fixed by Task 7; commit message documents intent. If you prefer green-only commits, squash Tasks 1+7 at the end instead.)

---

### Task 2: Alembic migration 056

**Files:**
- Create: `server/alembic/versions/056_org_llm_connector.py`

- [ ] **Step 1: Write the migration**

```python
"""Org-scoped LLM connector + llm_enabled rescope cleanup.

- llm_connectors.scope ('user'|'org'), user_id nullable, CHECK org<->NULL user
- llm_audit_event.actor_user_id nullable (system-context calls)
- system_settings.llm_model dropped (display-only legacy)
- Backfill: if llm_default_connector_id points at the migration-047-seeded
  env-var connector ("Org Default (migrated from env var)"), convert that row
  to scope='org' (it was the house key). Any other user-scoped default is
  cleared — an admin must create a proper org connector.

Revision ID: 056
Revises: 055
"""

import sqlalchemy as sa

from alembic import op

revision: str = "056"
down_revision: str | None = "055"
branch_labels = None
depends_on = None

_MIGRATED_DISPLAY_NAME = "Org Default (migrated from env var)"


def upgrade() -> None:
    op.add_column(
        "llm_connectors",
        sa.Column("scope", sa.String(10), nullable=False, server_default="user"),
    )
    op.alter_column("llm_connectors", "user_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("llm_audit_event", "actor_user_id", existing_type=sa.Integer(), nullable=True)
    op.drop_column("system_settings", "llm_model")

    # Backfill BEFORE adding the CHECK so the converted row satisfies it.
    conn = op.get_bind()
    default_id = conn.execute(
        sa.text("SELECT llm_default_connector_id FROM system_settings LIMIT 1")
    ).scalar()
    if default_id is not None:
        row = conn.execute(
            sa.text("SELECT id, display_name FROM llm_connectors WHERE id = :cid"),
            {"cid": default_id},
        ).first()
        if row is not None and row[1] == _MIGRATED_DISPLAY_NAME:
            conn.execute(
                sa.text(
                    "UPDATE llm_connectors SET scope = 'org', user_id = NULL WHERE id = :cid"
                ),
                {"cid": default_id},
            )
        elif row is not None:
            conn.execute(
                sa.text("UPDATE system_settings SET llm_default_connector_id = NULL")
            )

    op.create_check_constraint(
        "ck_llm_connectors_org_scope_no_user",
        "llm_connectors",
        "(scope = 'org') = (user_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_llm_connectors_org_scope_no_user", "llm_connectors", type_="check"
    )
    # Org rows cannot survive a NOT NULL user_id; clear default + delete them.
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE system_settings SET llm_default_connector_id = NULL "
            "WHERE llm_default_connector_id IN "
            "(SELECT id FROM llm_connectors WHERE scope = 'org')"
        )
    )
    conn.execute(sa.text("DELETE FROM llm_connectors WHERE scope = 'org'"))
    op.add_column(
        "system_settings",
        sa.Column(
            "llm_model",
            sa.String(100),
            nullable=False,
            server_default="claude-haiku-4-5-20251001",
        ),
    )
    op.alter_column("llm_audit_event", "actor_user_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("llm_connectors", "user_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("llm_connectors", "scope")
```

- [ ] **Step 2: Verify against a scratch Postgres (NOT the live testing DB on 5432)**

```bash
docker run --rm -d --name wrzdj-mig-test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=wrzdj -p 5433:5432 postgres:16
sleep 3
cd /home/adam/github/WrzDJ-worktrees/org-llm/server
SCRATCH_URL="postgresql://postgres:test@localhost:5433/wrzdj"
DATABASE_URL=$SCRATCH_URL $VENV/bin/alembic upgrade head
DATABASE_URL=$SCRATCH_URL $VENV/bin/alembic check
docker stop wrzdj-mig-test
```

Expected: `upgrade head` runs through 056 cleanly; `alembic check` reports no new upgrade operations. (Match the URL scheme — `postgresql://` vs `postgresql+psycopg://` — to whatever the main `.env` `DATABASE_URL` uses; if `alembic check` flags drift, the model and migration disagree — fix before continuing.)

- [ ] **Step 3: Commit**

```bash
cd /home/adam/github/WrzDJ-worktrees/org-llm
git add server/alembic/versions/056_org_llm_connector.py
git commit -m "feat(llm): migration 056 — org connector scope + audit actor nullability + backfill"
```

---

### Task 3: connector_storage — scope-aware helpers

**Files:**
- Modify: `server/app/services/llm/connector_storage.py`
- Test: `server/tests/test_llm_org_connector.py` (create)

- [ ] **Step 1: Write failing tests for the storage layer**

Create `server/tests/test_llm_org_connector.py`:

```python
"""Org-scoped connector storage + resolution tests (org-llm-connector spec)."""

from __future__ import annotations

import json

import pytest

from app.models.llm_connector import SCOPE_ORG, SCOPE_USER, STATUS_ACTIVE, LlmConnector
from app.services.llm.connector_storage import (
    CreateConnectorPayload,
    create_connector,
    get_user_label,
    list_connectors_for_user,
    list_org_connectors,
)


def _payload(name: str = "Org Key") -> CreateConnectorPayload:
    return CreateConnectorPayload(
        connector_type="anthropic_apikey",
        display_name=name,
        credentials={"api_key": "sk-ant-test-0000000000000000"},
        base_url_plain=None,
        model_hint=None,
    )


def test_create_org_connector_has_null_user_and_org_scope(db):
    from sqlalchemy import text

    row = create_connector(db, user_id=None, payload=_payload(), scope=SCOPE_ORG)
    db.commit()
    assert row.user_id is None
    assert row.scope == SCOPE_ORG
    assert row.status == STATUS_ACTIVE
    # Credentials encrypted at rest: raw column value must not contain the key.
    raw = db.execute(
        text("SELECT credentials FROM llm_connectors WHERE id = :i"), {"i": row.id}
    ).scalar()
    assert "sk-ant-test" not in (raw or "")


def test_create_user_connector_defaults_to_user_scope(db, test_user):
    row = create_connector(db, user_id=test_user.id, payload=_payload("Mine"))
    db.commit()
    assert row.scope == SCOPE_USER
    assert row.user_id == test_user.id


def test_list_org_connectors_excludes_user_rows(db, test_user):
    create_connector(db, user_id=test_user.id, payload=_payload("Mine"))
    org = create_connector(db, user_id=None, payload=_payload("House"), scope=SCOPE_ORG)
    db.commit()
    rows = list_org_connectors(db)
    assert [r.id for r in rows] == [org.id]


def test_list_connectors_for_user_excludes_org_rows(db, test_user):
    mine = create_connector(db, user_id=test_user.id, payload=_payload("Mine"))
    create_connector(db, user_id=None, payload=_payload("House"), scope=SCOPE_ORG)
    db.commit()
    rows = list_connectors_for_user(db, test_user.id)
    assert [r.id for r in rows] == [mine.id]


def test_get_user_label_for_org_rows(db):
    assert get_user_label(db, None) == "Organization"
```

(Adjust the encryption assertion to match how other tests assert `EncryptedText` — see `server/tests/test_llm_api.py` for the existing pattern and copy it; the intent is "raw DB value does not contain the plaintext key". If no clean pattern exists, drop that assertion — encryption is already covered by existing EncryptedText tests.)

- [ ] **Step 2: Run to verify failure**

```bash
cd /home/adam/github/WrzDJ-worktrees/org-llm/server
$VENV/bin/pytest tests/test_llm_org_connector.py -q
```

Expected: FAIL — `ImportError: cannot import name 'list_org_connectors'` / `create_connector() got an unexpected keyword argument 'scope'`.

- [ ] **Step 3: Implement storage changes**

In `server/app/services/llm/connector_storage.py`:

Import the scope constants (extend the existing model import):

```python
from app.models.llm_connector import (  # noqa: existing imports retained
    SCOPE_ORG,
    SCOPE_USER,
    ...
)
```

Add `scope` filter to `list_connectors_for_user` (line 51):

```python
def list_connectors_for_user(db: Session, user_id: int) -> list[LlmConnector]:
    return (
        db.query(LlmConnector)
        .filter(LlmConnector.user_id == user_id, LlmConnector.scope == SCOPE_USER)
        .order_by(LlmConnector.created_at.desc())
        .all()
    )
```

Add after `list_all_connectors`:

```python
def list_org_connectors(db: Session) -> list[LlmConnector]:
    return (
        db.query(LlmConnector)
        .filter(LlmConnector.scope == SCOPE_ORG)
        .order_by(LlmConnector.created_at.desc())
        .all()
    )
```

Change `create_connector` (line 368):

```python
def create_connector(
    db: Session,
    *,
    user_id: int | None,
    payload: CreateConnectorPayload,
    scope: str = SCOPE_USER,
) -> LlmConnector:
    """Persist a new connector. Caller is responsible for audit event + commit.

    Org-scoped rows (scope='org') must pass user_id=None — the DB CHECK
    enforces it; this assert catches programming errors early.
    """
    assert (scope == SCOPE_ORG) == (user_id is None), "org scope requires user_id=None"
    row = LlmConnector(
        user_id=user_id,
        scope=scope,
        connector_type=payload.connector_type,
        display_name=payload.display_name,
        status=STATUS_ACTIVE,
        credentials=json.dumps(payload.credentials),
        base_url_plain=payload.base_url_plain,
        model_hint=payload.model_hint,
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    return row
```

Change `get_user_label` (line 666):

```python
def get_user_label(db: Session, user_id: int | None) -> str:
    if user_id is None:
        return "Organization"
    user = db.get(User, user_id)
    return user.username if user else f"user#{user_id}"
```

Change `audit_event` (line 599) to accept a nullable actor:

```python
def audit_event(
    db: Session,
    *,
    actor_user_id: int | None,
    target_connector_id: int | None,
    event_type: str,
) -> LlmAuditEvent:
```

(body unchanged)

- [ ] **Step 4: Run tests to verify pass**

```bash
$VENV/bin/pytest tests/test_llm_org_connector.py tests/test_llm_api.py -q
```

Expected: new tests PASS; `test_llm_api.py` still PASSES (DJ listing now filters scope, behavior identical for user rows).

- [ ] **Step 5: Commit**

```bash
cd /home/adam/github/WrzDJ-worktrees/org-llm
git add server/app/services/llm/connector_storage.py server/tests/test_llm_org_connector.py
git commit -m "feat(llm): scope-aware connector storage + org helpers"
```

---

### Task 4: Gateway — scoped resolution, gated org fallback, NULL system actor

**Files:**
- Modify: `server/app/services/llm/gateway.py`
- Test: `server/tests/test_llm_gateway.py` (extend)

- [ ] **Step 1: Write failing gateway tests**

Append to `server/tests/test_llm_gateway.py` (reuse the file's existing `_make_connector` helper and `_patch_chat` — read its current signature first and pass `scope`/`user_id` accordingly; extend `_make_connector` with `scope: str = "user"` and `user_id: int | None` if needed):

```python
class TestOrgScopedResolution:
    @pytest.mark.asyncio
    async def test_byo_dj_dispatch_works_with_llm_enabled_false(self, db, dj_user, gateway_request):
        """HEADLINE REGRESSION: a DJ's own connector is never blocked by llm_enabled."""
        _make_connector(db, user_id=dj_user.id)
        settings = db.query(SystemSettings).first() or SystemSettings()
        settings.llm_enabled = False
        db.add(settings)
        db.commit()

        with _patch_chat(AsyncMock(return_value=_ok_response())):
            resp = await Gateway.dispatch(db, dj_user, gateway_request, purpose="recommendation")
        assert resp is not None

    @pytest.mark.asyncio
    async def test_connectorless_dj_blocked_when_llm_enabled_false(self, db, dj_user, gateway_request):
        org = _make_connector(db, user_id=None, scope="org")
        settings = db.query(SystemSettings).first() or SystemSettings()
        settings.llm_enabled = False
        settings.llm_default_connector_id = org.id
        db.add(settings)
        db.commit()

        with pytest.raises(NoLlmConfigured):
            await Gateway.dispatch(db, dj_user, gateway_request, purpose="recommendation")

    @pytest.mark.asyncio
    async def test_connectorless_dj_uses_org_fallback_when_enabled(self, db, dj_user, gateway_request):
        org = _make_connector(db, user_id=None, scope="org")
        settings = db.query(SystemSettings).first() or SystemSettings()
        settings.llm_enabled = True
        settings.llm_default_connector_id = org.id
        db.add(settings)
        db.commit()

        with _patch_chat(AsyncMock(return_value=_ok_response())):
            resp = await Gateway.dispatch(db, dj_user, gateway_request, purpose="recommendation")
        assert resp is not None

    @pytest.mark.asyncio
    async def test_user_scoped_default_never_resolves_as_org_fallback(self, db, dj_user, gateway_request):
        """A user-scoped connector configured as default must NOT serve fallback."""
        other = _make_connector(db, user_id=dj_user.id)  # someone's personal key
        settings = db.query(SystemSettings).first() or SystemSettings()
        settings.llm_enabled = True
        settings.llm_default_connector_id = other.id
        db.add(settings)
        db.commit()

        system_actorless = None
        with pytest.raises(NoLlmConfigured):
            await Gateway.dispatch(db, system_actorless, gateway_request, purpose="recommendation")

    @pytest.mark.asyncio
    async def test_system_context_audit_actor_is_null_on_auth_failure(self, db, gateway_request):
        from app.models.llm_connector import LlmAuditEvent

        org = _make_connector(db, user_id=None, scope="org")
        settings = db.query(SystemSettings).first() or SystemSettings()
        settings.llm_enabled = True
        settings.llm_default_connector_id = org.id
        db.add(settings)
        db.commit()

        with _patch_chat(AsyncMock(side_effect=AuthInvalid("nope"))):
            with pytest.raises(AuthInvalid):
                await Gateway.dispatch(db, None, gateway_request, purpose="recommendation")

        event = (
            db.query(LlmAuditEvent)
            .filter(LlmAuditEvent.target_connector_id == org.id)
            .order_by(LlmAuditEvent.id.desc())
            .first()
        )
        assert event is not None
        assert event.actor_user_id is None
```

Adapt fixture/helper names to the file's actual ones (`_ok_response` may be a local helper or inline `ChatResponse(...)` — copy the construction used by existing passing tests in that file).

- [ ] **Step 2: Run to verify failure**

```bash
$VENV/bin/pytest tests/test_llm_gateway.py -q 2>&1 | tail -5
```

Expected: new tests FAIL (`_make_connector` lacks scope, BYO test fails because `llm_enabled=False`… wait — today the gateway does NOT check llm_enabled, so the BYO test may pass already; the org-gating tests must fail). At least `test_connectorless_dj_blocked_when_llm_enabled_false` and `test_user_scoped_default_never_resolves_as_org_fallback` FAIL.

- [ ] **Step 3: Implement gateway changes**

In `server/app/services/llm/gateway.py`:

Import scope constants (extend existing model import at line 35):

```python
from app.models.llm_connector import (
    AUDIT_AUTH_INVALID_OBSERVED,
    SCOPE_ORG,
    SCOPE_USER,
    STATUS_ACTIVE,
    STATUS_AUTH_INVALID,
    LlmConnector,
)
```

In `_resolve_connector` (line 423), add `LlmConnector.scope == SCOPE_USER` to BOTH per-DJ queries (the `pinned` query and the MRU `row` query), and to the feature-pin validity check:

```python
            if (
                pinned_feature is not None
                and pinned_feature.user_id == actor.id
                and pinned_feature.scope == SCOPE_USER
                and pinned_feature.status == STATUS_ACTIVE
            ):
```

```python
        pinned = (
            db.query(LlmConnector)
            .filter(
                LlmConnector.user_id == actor.id,
                LlmConnector.scope == SCOPE_USER,
                LlmConnector.status == STATUS_ACTIVE,
                LlmConnector.is_default == True,  # noqa: E712
            )
            .first()
        )
```

```python
        row = (
            db.query(LlmConnector)
            .filter(
                LlmConnector.user_id == actor.id,
                LlmConnector.scope == SCOPE_USER,
                LlmConnector.status == STATUS_ACTIVE,
            )
            .order_by(nulls_last(desc(LlmConnector.last_used_at)), desc(LlmConnector.id))
            .first()
        )
```

Replace `_resolve_org_default` (line 476):

```python
def _resolve_org_default(db: Session) -> LlmConnector | None:
    """Active org-scoped default, gated by the org-fallback policy toggle.

    ``llm_enabled`` governs ONLY this path: DJs with their own connector are
    resolved earlier and never reach here. Returns ``None`` when the toggle is
    off, no default is set, or the default is not an active org-scoped row.
    """
    settings = db.query(SystemSettings).first()
    if not settings or not settings.llm_enabled or not settings.llm_default_connector_id:
        return None
    default = db.get(LlmConnector, settings.llm_default_connector_id)
    if default is not None and default.scope == SCOPE_ORG and default.status == STATUS_ACTIVE:
        return default
    return None
```

Delete `_system_actor_id` entirely (lines 485-492). In `Gateway.dispatch` (line 121) and `Gateway.stream` (line 204) replace:

```python
        actor_id = actor.id if actor else _system_actor_id(db, primary)
```

with:

```python
        # NULL actor = system-context call; audit rows record no user rather
        # than misattributing usage to the connector's owner.
        actor_id = actor.id if actor else None
```

Update `_attempt` and `_attempt_stream` signatures: `actor_id: int` → `actor_id: int | None`.

- [ ] **Step 4: Run gateway + related suites**

```bash
$VENV/bin/pytest tests/test_llm_gateway.py tests/test_llm_gateway_stream.py tests/test_llm_default_connector.py tests/test_llm_feature_preference.py tests/test_llm_quota_cap.py -q
```

Expected: PASS. `test_llm_default_connector.py` likely seeds a USER-scoped connector as org default and expects fallback — those tests now describe forbidden behavior: update them to seed the default connector with `scope="org", user_id=None` (the legitimate equivalent), keeping their fallback assertions.

- [ ] **Step 5: Commit**

```bash
git add server/app/services/llm/gateway.py server/tests/test_llm_gateway.py server/tests/test_llm_default_connector.py
git commit -m "feat(llm): scope-filtered resolution, llm_enabled gates org fallback only, NULL system actor"
```

---

### Task 5: `is_llm_available` rewrite

**Files:**
- Modify: `server/app/services/recommendation/llm_hooks.py:67-113`
- Test: `server/tests/test_llm_hooks.py` (extend/update)

- [ ] **Step 1: Write failing tests**

In `server/tests/test_llm_hooks.py`, add (mirror existing fixture style in the file):

```python
def test_available_for_byo_dj_even_when_llm_disabled(db, test_user):
    from app.models.llm_connector import LlmConnector
    from app.services.recommendation.llm_hooks import is_llm_available

    db.add(
        LlmConnector(
            user_id=test_user.id,
            connector_type="anthropic_apikey",
            display_name="Mine",
            status="active",
            credentials="{}",
        )
    )
    settings = get_system_settings(db)
    settings.llm_enabled = False
    db.commit()
    assert is_llm_available(db, actor=test_user) is True


def test_unavailable_for_connectorless_dj_when_llm_disabled(db, test_user):
    from app.models.llm_connector import LlmConnector
    from app.services.recommendation.llm_hooks import is_llm_available

    org = LlmConnector(
        user_id=None,
        scope="org",
        connector_type="anthropic_apikey",
        display_name="House",
        status="active",
        credentials="{}",
    )
    db.add(org)
    db.flush()
    settings = get_system_settings(db)
    settings.llm_enabled = False
    settings.llm_default_connector_id = org.id
    db.commit()
    assert is_llm_available(db, actor=test_user) is False


def test_available_via_org_fallback_when_enabled(db, test_user):
    from app.models.llm_connector import LlmConnector
    from app.services.recommendation.llm_hooks import is_llm_available

    org = LlmConnector(
        user_id=None,
        scope="org",
        connector_type="anthropic_apikey",
        display_name="House",
        status="active",
        credentials="{}",
    )
    db.add(org)
    db.flush()
    settings = get_system_settings(db)
    settings.llm_enabled = True
    settings.llm_default_connector_id = org.id
    db.commit()
    assert is_llm_available(db, actor=test_user) is True
```

(Import `get_system_settings` from `app.services.system_settings` at the top if not already imported.)

- [ ] **Step 2: Run to verify failure**

```bash
$VENV/bin/pytest tests/test_llm_hooks.py -q
```

Expected: `test_available_for_byo_dj_even_when_llm_disabled` FAILS (current code returns False on the global flag).

- [ ] **Step 3: Replace `is_llm_available` body**

```python
def is_llm_available(db=None, actor=None) -> bool:
    """Check if LLM features are available for this actor.

    Mirrors :func:`app.services.llm.gateway._resolve_connector` semantics:

    - A DJ with an active connector of their own is ALWAYS available —
      ``llm_enabled`` does not apply to BYO credentials.
    - Otherwise availability equals the gated org fallback: an active
      org-scoped default connector AND ``llm_enabled`` true.

    Connector-backed only. Without ``db`` no connector can be resolved, so it
    returns ``False`` — the legacy Anthropic env-var fallback was removed in #343.
    """
    if db is None:
        return False

    from app.models.llm_connector import SCOPE_USER, STATUS_ACTIVE, LlmConnector
    from app.services.llm.gateway import _resolve_org_default

    if actor is not None:
        actor_active = (
            db.query(LlmConnector.id)
            .filter(
                LlmConnector.user_id == actor.id,
                LlmConnector.scope == SCOPE_USER,
                LlmConnector.status == STATUS_ACTIVE,
            )
            .first()
        )
        if actor_active is not None:
            return True

    return _resolve_org_default(db) is not None
```

Remove the now-unused `SystemSettings` import inside the old body.

- [ ] **Step 4: Run to verify pass + commit**

```bash
$VENV/bin/pytest tests/test_llm_hooks.py tests/test_llm_recommendation_via_gateway.py -q
git add server/app/services/recommendation/llm_hooks.py server/tests/test_llm_hooks.py
git commit -m "feat(llm): is_llm_available — BYO DJs never blocked by llm_enabled"
```

---

### Task 6: Policy validation + audit schema nullability

**Files:**
- Modify: `server/app/api/admin_llm.py` (patch_policy, _audit_query consumers, _connector_to_admin_out, list_connectors_admin, get_usage)
- Modify: `server/app/schemas/llm.py` (ConnectorOut.user_id, AuditEventRow.actor_user_id, UsageRow.dj_username semantics)
- Test: `server/tests/test_llm_org_connector.py` (extend), `server/tests/test_llm_admin_audit.py` (update if needed)

- [ ] **Step 1: Write failing tests**

Append to `server/tests/test_llm_org_connector.py`:

```python
def _mk_user_connector(db, user_id):
    row = LlmConnector(
        user_id=user_id,
        connector_type="anthropic_apikey",
        display_name="Personal",
        status="active",
        credentials="{}",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _mk_org_connector(db, name="House"):
    row = LlmConnector(
        user_id=None,
        scope=SCOPE_ORG,
        connector_type="anthropic_apikey",
        display_name=name,
        status="active",
        credentials="{}",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_policy_rejects_user_scoped_default(client, admin_headers, db, test_user):
    personal = _mk_user_connector(db, test_user.id)
    resp = client.patch(
        "/api/admin/llm/policy",
        json={"llm_default_connector_id": personal.id},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert "org-scoped" in resp.json()["detail"]


def test_policy_accepts_org_scoped_default(client, admin_headers, db):
    org = _mk_org_connector(db)
    resp = client.patch(
        "/api/admin/llm/policy",
        json={"llm_default_connector_id": org.id},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["llm_default_connector_id"] == org.id


def test_admin_connector_list_labels_org_rows(client, admin_headers, db):
    _mk_org_connector(db, name="House Key")
    resp = client.get("/api/admin/llm/connectors", headers=admin_headers)
    assert resp.status_code == 200
    org_rows = [r for r in resp.json() if r["display_name"] == "House Key"]
    assert org_rows and org_rows[0]["dj_username"] == "Organization"
    assert org_rows[0]["user_id"] is None
```

- [ ] **Step 2: Run to verify failure**

```bash
$VENV/bin/pytest tests/test_llm_org_connector.py -q
```

Expected: FAIL — policy accepts user-scoped id (200 vs 400) and admin list crashes/mislabels NULL user rows.

- [ ] **Step 3: Implement**

`server/app/schemas/llm.py`:
- `ConnectorOut.user_id: int` → `user_id: int | None` (org rows have no owner).
- Add `scope` to `ConnectorOut`: `scope: Literal["user", "org"] = "user"` (import `Literal` if needed).
- `AuditEventRow.actor_user_id: int` → `actor_user_id: int | None`.

`server/app/api/admin_llm.py`:

In `patch_policy` (after the `status != "active"` check, line ~164):

```python
        if target.scope != "org":
            raise HTTPException(
                status_code=400,
                detail="default connector must be org-scoped (create one under Organization connector)",
            )
```

In `list_connectors_admin` (line 195): `user_ids = {r.user_id for r in rows if r.user_id is not None}` and the comprehension:

```python
    return [
        _connector_to_admin_out(
            r,
            "Organization" if r.user_id is None else (usernames.get(r.user_id) or f"user#{r.user_id}"),
            usage_by_connector.get(r.id, 0),
        )
        for r in rows
    ]
```

In `get_usage` (line 298): `user_ids = {c.user_id for c in connectors if c.user_id is not None}` and the row construction:

```python
                    dj_username=(
                        "Organization"
                        if c.user_id is None
                        else usernames.get(c.user_id, f"user#{c.user_id}")
                    ),
```

In `list_audit_events` (line 370): `actor_username=actor_username or ("system" if event.actor_user_id is None else f"user#{event.actor_user_id}")` — same fallback in `export_audit_events_csv` (line 429).

- [ ] **Step 4: Run to verify pass**

```bash
$VENV/bin/pytest tests/test_llm_org_connector.py tests/test_llm_admin_audit.py tests/test_llm_api.py -q
```

Expected: PASS (fix any audit-test fixtures that asserted non-null actor formats).

- [ ] **Step 5: Commit**

```bash
git add server/app/api/admin_llm.py server/app/schemas/llm.py server/tests/
git commit -m "feat(llm): policy requires org-scoped default; org rows labeled Organization"
```

---

### Task 7: Org connector CRUD endpoints + legacy admin surface removal

**Files:**
- Modify: `server/app/api/admin_llm.py` (new org endpoints)
- Modify: `server/app/api/admin.py:340-432` (slim AI settings, delete models endpoint)
- Modify: `server/app/schemas/ai_settings.py`
- Modify: `server/app/api/events.py:1007`
- Modify: `server/app/core/config.py:138-139`
- Test: `server/tests/test_llm_org_connector.py` (extend), existing admin tests (update)

- [ ] **Step 1: Write failing tests for org CRUD + legacy removal**

Append to `server/tests/test_llm_org_connector.py`:

```python
def test_org_crud_requires_admin(client, auth_headers):
    resp = client.get("/api/admin/llm/org-connectors", headers=auth_headers)
    assert resp.status_code == 403


def test_org_connector_create_list_delete(client, admin_headers):
    create = client.post(
        "/api/admin/llm/org-connectors",
        json={
            "connector_type": "anthropic_apikey",
            "display_name": "House Anthropic",
            "api_key": "sk-ant-api03-" + "a" * 40,
        },
        headers=admin_headers,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["user_id"] is None
    assert body["scope"] == "org"
    cid = body["id"]

    listed = client.get("/api/admin/llm/org-connectors", headers=admin_headers)
    assert [r["id"] for r in listed.json()] == [cid]

    deleted = client.delete(f"/api/admin/llm/org-connectors/{cid}", headers=admin_headers)
    assert deleted.status_code == 204
    assert client.get("/api/admin/llm/org-connectors", headers=admin_headers).json() == []


def test_ai_settings_no_longer_exposes_api_key_or_model(client, admin_headers):
    resp = client.get("/api/admin/ai/settings", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "api_key_configured" not in body
    assert "api_key_masked" not in body
    assert "llm_model" not in body
    assert set(body) == {"llm_enabled", "llm_rate_limit_per_minute"}


def test_ai_models_endpoint_removed(client, admin_headers):
    resp = client.get("/api/admin/ai/models", headers=admin_headers)
    assert resp.status_code == 404
```

(Match the `ConnectorCreate` body shape to `server/app/schemas/llm.py:91` — if `api_key` validation rejects the dummy key format, copy a key fixture from `tests/test_llm_api.py`.)

- [ ] **Step 2: Run to verify failure**

```bash
$VENV/bin/pytest tests/test_llm_org_connector.py -q
```

Expected: FAIL — 404 on org-connector routes; AI settings still returns legacy fields.

- [ ] **Step 3: Add org endpoints to `admin_llm.py`**

Imports to extend: `from app.schemas.llm import ConnectorCreate, ConnectorCredentialsRotate, ConnectorOut, ConnectorTestResult` (plus existing), `from app.services.llm.connector_storage import build_create_payload, create_connector, delete_connector, list_org_connectors, rotate_credentials` and `from app.models.llm_connector import AUDIT_CREATED, AUDIT_CREDENTIALS_ROTATED, AUDIT_DELETED`. (Check `rotate_credentials`' exact keyword list at `connector_storage.py:385` and pass only the fields it accepts.)

```python
# ---------- Organization connector (house-billed fallback) ----------


@router.get("/org-connectors", response_model=list[ConnectorOut])
@limiter.limit("60/minute")
def list_org_connectors_admin(
    request: FastAPIRequest,
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> list[ConnectorOut]:
    return [ConnectorOut.model_validate(r) for r in list_org_connectors(db)]


@router.post("/org-connectors", response_model=ConnectorOut, status_code=201)
@limiter.limit("10/minute")
def create_org_connector(
    request: FastAPIRequest,
    payload: ConnectorCreate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> ConnectorOut:
    """Create the organization's house connector (admin-only).

    Reuses the DJ-connector validation pipeline; the row is org-scoped with no
    owner. Credentials are encrypted at rest via EncryptedText.
    """
    try:
        create_payload = build_create_payload(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row = create_connector(db, user_id=None, payload=create_payload, scope="org")
    audit_event(
        db, actor_user_id=admin.id, target_connector_id=row.id, event_type=AUDIT_CREATED
    )
    db.commit()
    db.refresh(row)
    return ConnectorOut.model_validate(row)


@router.post("/org-connectors/{connector_id}/test", response_model=ConnectorTestResult)
@limiter.limit("10/minute")
async def test_org_connector(
    request: FastAPIRequest,
    connector_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> ConnectorTestResult:
    from app.services.llm.health_check import run_health_check

    row = get_connector(db, connector_id)
    if row is None or row.scope != "org":
        raise HTTPException(status_code=404, detail="Connector not found")
    outcome = await run_health_check(db, row, actor_user_id=admin.id)
    db.commit()
    if outcome.ok:
        return ConnectorTestResult(ok=True)
    message = {
        "auth_invalid": "Authentication failed against the provider",
        "rate_limited": "Provider rate limited the request",
        "quota_exceeded": "Provider quota or billing failure",
        "provider_unavailable": "Provider unreachable or timed out",
        "error": "Unknown error",
    }.get(outcome.status, "Unknown error")
    return ConnectorTestResult(ok=False, error_code=outcome.error_code or outcome.status, message=message)


@router.put("/org-connectors/{connector_id}/credentials", response_model=ConnectorOut)
@limiter.limit("10/minute")
def rotate_org_connector_credentials(
    request: FastAPIRequest,
    connector_id: int,
    payload: ConnectorCredentialsRotate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> ConnectorOut:
    """Rotate the house connector's credential blob (admin-only)."""
    row = get_connector(db, connector_id)
    if row is None or row.scope != "org":
        raise HTTPException(status_code=404, detail="Connector not found")
    try:
        rotate_credentials(
            db,
            connector=row,
            api_key=payload.api_key,
            base_url=payload.base_url,
            bearer=payload.bearer,
            aws_access_key_id=payload.aws_access_key_id,
            aws_secret_access_key=payload.aws_secret_access_key,
            aws_region=payload.aws_region,
            aws_model_id=payload.aws_model_id,
            azure_resource_name=payload.azure_resource_name,
            azure_deployment_name=payload.azure_deployment_name,
            azure_api_version=payload.azure_api_version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_event(
        db,
        actor_user_id=admin.id,
        target_connector_id=row.id,
        event_type=AUDIT_CREDENTIALS_ROTATED,
    )
    db.commit()
    db.refresh(row)
    return ConnectorOut.model_validate(row)


@router.delete("/org-connectors/{connector_id}", status_code=204)
@limiter.limit("10/minute")
def delete_org_connector(
    request: FastAPIRequest,
    connector_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> None:
    row = get_connector(db, connector_id)
    if row is None or row.scope != "org":
        raise HTTPException(status_code=404, detail="Connector not found")
    audit_event(
        db, actor_user_id=admin.id, target_connector_id=row.id, event_type=AUDIT_DELETED
    )
    settings = get_system_settings(db)
    if settings.llm_default_connector_id == row.id:
        settings.llm_default_connector_id = None
    delete_connector(db, row)
    db.commit()
```

(`build_create_payload`'s exact signature is at `connector_storage.py:136` — adapt the call if it takes the schema plus flags; mirror how `create_connector_endpoint` in `api/llm.py:219` calls it, including the connector-type policy check `_check_connector_type_allowed` if appropriate for org rows — org connectors are admin-created, so skip the DJ-facing type-policy check.)

- [ ] **Step 4: Slim the legacy admin AI surface**

`server/app/schemas/ai_settings.py` — replace the whole file body with:

```python
"""Schemas for AI/LLM admin settings."""

from pydantic import BaseModel, Field


class AIModelInfo(BaseModel):
    id: str
    name: str


class AIModelsResponse(BaseModel):
    models: list[AIModelInfo]


class AISettingsOut(BaseModel):
    llm_enabled: bool
    llm_rate_limit_per_minute: int


class AISettingsUpdate(BaseModel):
    llm_enabled: bool | None = None
    llm_rate_limit_per_minute: int | None = Field(None, ge=1, le=30)
```

(`AIModelInfo`/`AIModelsResponse` stay — `GET /api/llm/openrouter/models` uses them.)

`server/app/api/admin.py`:
- Delete `_mask_api_key`, `_list_anthropic_models`, the `FALLBACK_MODELS` constant (lines ~56-59), and the `GET /ai/models` endpoint.
- Remove `AIModelInfo`/`AIModelsResponse` imports if now unused in this file.
- Rewrite the two settings endpoints:

```python
@router.get("/ai/settings", response_model=AISettingsOut)
@limiter.limit("120/minute")
def admin_get_ai_settings(
    request: FastAPIRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> AISettingsOut:
    """Get AI/LLM configuration.

    ``llm_enabled`` gates only the org-connector fallback — DJs with their own
    connector are never blocked by it. Credential status lives on the
    connector surfaces (/api/admin/llm/*), not here.
    """
    settings = get_system_settings(db)
    return AISettingsOut(
        llm_enabled=settings.llm_enabled,
        llm_rate_limit_per_minute=settings.llm_rate_limit_per_minute,
    )


@router.put("/ai/settings", response_model=AISettingsOut)
@limiter.limit("30/minute")
def admin_update_ai_settings(
    update_data: AISettingsUpdate,
    request: FastAPIRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> AISettingsOut:
    """Update AI/LLM configuration."""
    settings = update_system_settings(
        db,
        llm_enabled=update_data.llm_enabled,
        llm_rate_limit_per_minute=update_data.llm_rate_limit_per_minute,
    )
    return AISettingsOut(
        llm_enabled=settings.llm_enabled,
        llm_rate_limit_per_minute=settings.llm_rate_limit_per_minute,
    )
```

`server/app/api/events.py:1007`:

```python
        llm_model=result.llm_model or "",
```

(then remove the `get_settings` import in events.py ONLY if `grep -n "get_settings" server/app/api/events.py` shows no other use).

`server/app/core/config.py`:
- Delete the `anthropic_api_key: str = ""` field (line 138).
- Replace the `anthropic_model` line's context with:

```python
    # Retained ONLY for migration 047_admin_ai_oauth (model_hint on the seeded
    # connector). No runtime consumer — do not reference in app code.
    anthropic_model: str = "claude-haiku-4-5-20251001"
```

- [ ] **Step 5: Sweep for stragglers**

```bash
cd /home/adam/github/WrzDJ-worktrees/org-llm/server
grep -rn "anthropic_api_key\|api_key_configured\|api_key_masked\|_list_anthropic_models\|FALLBACK_MODELS" app/ tests/ --include="*.py" | grep -v alembic
grep -rn "llm_model" app/api/admin.py tests/ --include="*.py" | grep -v track_vibe | grep -v recommendation
```

Fix every hit (test files asserting the old AI settings shape get updated to the new two-field shape).

- [ ] **Step 6: Run the backend suite**

```bash
$VENV/bin/pytest --tb=short -q 2>&1 | tail -10
```

Expected: PASS, coverage ≥ 85%.

- [ ] **Step 7: Commit**

```bash
git add server/
git commit -m "feat(llm): org connector CRUD; remove legacy Anthropic env-var admin surface"
```

---

### Task 8: Per-DJ effective-source endpoint + DJ-visible fallback flag

**Files:**
- Modify: `server/app/api/admin_llm.py` (dj-status endpoint)
- Modify: `server/app/api/llm.py` (`get_dj_policy`)
- Modify: `server/app/schemas/llm.py` (new schemas + DjPolicyOut field)
- Test: `server/tests/test_llm_org_connector.py` (extend)

- [ ] **Step 1: Write failing tests**

```python
def test_dj_status_reports_effective_source(client, admin_headers, db, test_user):
    org = _mk_org_connector(db)
    settings = get_system_settings(db)
    settings.llm_enabled = True
    settings.llm_default_connector_id = org.id
    db.commit()

    resp = client.get("/api/admin/llm/dj-status", headers=admin_headers)
    assert resp.status_code == 200
    by_name = {r["username"]: r["effective_source"] for r in resp.json()["rows"]}
    assert by_name[test_user.username] == "org_fallback"

    _mk_user_connector(db, test_user.id)
    resp = client.get("/api/admin/llm/dj-status", headers=admin_headers)
    by_name = {r["username"]: r["effective_source"] for r in resp.json()["rows"]}
    assert by_name[test_user.username] == "own"


def test_dj_policy_exposes_org_fallback_available(client, auth_headers, db):
    resp = client.get("/api/llm/policy", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["org_fallback_available"] is False

    org = _mk_org_connector(db)
    settings = get_system_settings(db)
    settings.llm_enabled = True
    settings.llm_default_connector_id = org.id
    db.commit()
    resp = client.get("/api/llm/policy", headers=auth_headers)
    assert resp.json()["org_fallback_available"] is True
```

(Add `from app.services.system_settings import get_system_settings` to the test file imports. The DJ policy route path is `GET /api/llm/policy` — confirm the actual mounted path from `server/app/api/llm.py:169-178` and `main.py` router prefix; adjust the test URL if it differs.)

- [ ] **Step 2: Run to verify failure, then implement**

Schemas (`server/app/schemas/llm.py`):

```python
class DjLlmStatusRow(BaseModel):
    user_id: int
    username: str
    effective_source: Literal["own", "org_fallback", "none"]


class DjLlmStatusOut(BaseModel):
    rows: list[DjLlmStatusRow]
```

Add to `DjPolicyOut`:

```python
    # True when an active org-scoped default exists AND llm_enabled is on —
    # i.e. a connector-less DJ will fall back to the house connector.
    org_fallback_available: bool = False
```

Endpoint in `admin_llm.py`:

```python
@router.get("/dj-status", response_model=DjLlmStatusOut)
@limiter.limit("60/minute")
def dj_llm_status(
    request: FastAPIRequest,
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> DjLlmStatusOut:
    """Effective LLM credential source per DJ — backend-computed so the admin
    UI never duplicates gateway resolution rules."""
    from app.services.llm.gateway import _resolve_org_default

    fallback_on = _resolve_org_default(db) is not None
    users = (
        db.query(User)
        .filter(User.role.in_(["dj", "admin"]))
        .order_by(User.username.asc())
        .all()
    )
    own_ids = {
        uid
        for (uid,) in db.query(LlmConnector.user_id)
        .filter(LlmConnector.scope == "user", LlmConnector.status == "active")
        .distinct()
        .all()
    }
    rows = [
        DjLlmStatusRow(
            user_id=u.id,
            username=u.username,
            effective_source=(
                "own" if u.id in own_ids else ("org_fallback" if fallback_on else "none")
            ),
        )
        for u in users
    ]
    return DjLlmStatusOut(rows=rows)
```

In `api/llm.py` `get_dj_policy`, compute and include the flag:

```python
    from app.services.llm.gateway import _resolve_org_default

    ...
    return DjPolicyOut(
        ...,
        org_fallback_available=_resolve_org_default(db) is not None,
    )
```

- [ ] **Step 3: Run, then commit**

```bash
$VENV/bin/pytest tests/test_llm_org_connector.py tests/test_llm_api.py -q
git add server/
git commit -m "feat(llm): per-DJ effective-source endpoint + org_fallback_available on DJ policy"
```

---

### Task 9: OpenAPI + generated types regeneration

**Files:**
- Regenerate: `server/openapi.json`, `dashboard/lib/api-types.generated.ts`

- [ ] **Step 1: Regenerate**

```bash
cd /home/adam/github/WrzDJ-worktrees/org-llm/dashboard
npm run types:export && npm run types:generate
```

(If `types:export` invokes `.venv/bin/python` relative to `../server`, and the worktree has no venv, run the export with the main venv: `cd ../server && $VENV/bin/python scripts/export_openapi.py`, then `cd ../dashboard && npm run types:generate`.)

- [ ] **Step 2: Commit**

```bash
git add server/openapi.json dashboard/lib/api-types.generated.ts
git commit -m "chore(types): regenerate OpenAPI schema + frontend types for org connector API"
```

---

### Task 10: Frontend API client + hand-written types

**Files:**
- Modify: `dashboard/lib/api.ts` (~lines 1381-1400, 1560)
- Modify: `dashboard/lib/api-types.ts` (hand-written types, if AISettings/LlmConnector/DjPolicy live here — grep first)

- [ ] **Step 1: Locate the hand-written types**

```bash
cd /home/adam/github/WrzDJ-worktrees/org-llm/dashboard
grep -rn "api_key_configured\|AISettings\b\|interface LlmConnector\|DjPolicy" lib/*.ts | grep -v generated | grep -v test
```

- [ ] **Step 2: Apply type changes**

- `AISettings`: remove `api_key_configured`, `api_key_masked`, `llm_model`; keep `llm_enabled`, `llm_rate_limit_per_minute`. Same for `AISettingsUpdate`.
- `LlmConnector` (or `ConnectorOut`-equivalent): `user_id: number | null`, add `scope: 'user' | 'org'`.
- `DjPolicy` (DJ policy type): add `org_fallback_available: boolean`.
- New types:

```typescript
export interface DjLlmStatusRow {
  user_id: number;
  username: string;
  effective_source: 'own' | 'org_fallback' | 'none';
}

export interface DjLlmStatusResponse {
  rows: DjLlmStatusRow[];
}
```

- [ ] **Step 3: API client methods**

In `dashboard/lib/api.ts`: delete `getAIModels()` (line 1381). Add next to the admin LLM methods (~line 1560):

```typescript
  async listOrgConnectors(): Promise<LlmConnector[]> {
    return this.fetch('/api/admin/llm/org-connectors');
  }

  async createOrgConnector(data: LlmConnectorCreate): Promise<LlmConnector> {
    return this.fetch('/api/admin/llm/org-connectors', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async testOrgConnector(id: number): Promise<ConnectorTestResult> {
    return this.fetch(`/api/admin/llm/org-connectors/${id}/test`, { method: 'POST' });
  }

  async deleteOrgConnector(id: number): Promise<void> {
    await this.fetch(`/api/admin/llm/org-connectors/${id}`, { method: 'DELETE' });
  }

  async getDjLlmStatus(): Promise<DjLlmStatusResponse> {
    return this.fetch('/api/admin/llm/dj-status');
  }
```

(Match the surrounding methods' exact `this.fetch` idiom — some return `this.fetch<T>(...)`; copy the file's convention. `LlmConnectorCreate`/`ConnectorTestResult` type names: reuse whatever the existing `createLlmConnector`/`testLlmConnector` methods use.)

- [ ] **Step 4: Type check + commit**

```bash
npx tsc --noEmit
```

Expected: errors ONLY in the two pages still referencing removed fields (`admin/ai/page.tsx`, possibly `AiProvidersSection.tsx`) — those are the next tasks. If errors appear elsewhere, fix them now.

```bash
git add dashboard/lib/
git commit -m "feat(dashboard): org connector API client; drop legacy AI key/model types"
```

---

### Task 11: Admin AI page rework

**Files:**
- Modify: `dashboard/app/admin/ai/page.tsx`
- Test: `dashboard/app/admin/ai/__tests__/page.test.tsx`

- [ ] **Step 1: Update the page test first**

In `dashboard/app/admin/ai/__tests__/page.test.tsx`:
- Update the `api` mock: remove `getAIModels`; `getAISettings` resolves `{ llm_enabled: true, llm_rate_limit_per_minute: 3 }`; add `listOrgConnectors: vi.fn().mockResolvedValue([])`, `createOrgConnector`, `testOrgConnector`, `deleteOrgConnector`, `getDjLlmStatus: vi.fn().mockResolvedValue({ rows: [] })`.
- Delete assertions on "API Key Status" / "Configured" / model select.
- Add:

```tsx
it('does not render the legacy API Key Status panel', async () => {
  render(<AdminAiPage />);
  await waitFor(() => expect(screen.queryByText('API Key Status')).not.toBeInTheDocument());
});

it('renders the Organization connector section', async () => {
  render(<AdminAiPage />);
  await waitFor(() => expect(screen.getByText('Organization connector')).toBeInTheDocument());
});

it('renders effective-source badges from dj-status', async () => {
  vi.mocked(api.getDjLlmStatus).mockResolvedValue({
    rows: [{ user_id: 1, username: 'djtest', effective_source: 'org_fallback' }],
  });
  render(<AdminAiPage />);
  await waitFor(() => expect(screen.getByText('Org fallback')).toBeInTheDocument());
});
```

Run: `npx vitest run app/admin/ai --reporter=dot` → expected FAIL.

- [ ] **Step 2: Rework the page**

In `dashboard/app/admin/ai/page.tsx`:

1. **Delete** the API Key Status card (lines ~478-506, the `HelpSpot spotId="admin-ai-key"` block) and any model-select UI + `getAIModels()` fetch + related state.
2. **Recopy the enable toggle** (the `admin-ai-enable` HelpSpot): label text becomes `Allow DJs without their own connector to use the organization connector (house-billed)` and the HelpSpot description: `When off, only DJs who connected their own provider can use AI features. DJs' own connectors are never blocked by this switch.`
3. **Add an "Organization connector" card** above the policy section:

```tsx
<div className="card">
  <h2 style={{ marginBottom: '0.5rem' }}>Organization connector</h2>
  <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '1rem' }}>
    The house credential. DJs without their own connector fall back to it when the
    toggle below allows — usage is billed to the organization.
  </p>
  {orgConnectors.length === 0 ? (
    <OrgConnectorForm onCreated={reloadOrgConnectors} />
  ) : (
    orgConnectors.map((c) => (
      <div key={c.id} style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <strong>{c.display_name}</strong>
        <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
          {TYPE_LABELS[c.connector_type] ?? c.connector_type}
          {c.model_hint ? ` · ${c.model_hint}` : ''}
        </span>
        <span
          style={{
            padding: '0.25rem 0.75rem', borderRadius: '9999px', fontSize: '0.75rem', fontWeight: 600,
            background: c.status === 'active' ? 'var(--color-success-subtle)' : 'var(--color-danger-subtle)',
            color: c.status === 'active' ? 'var(--color-success)' : 'var(--color-danger)',
          }}
        >
          {c.status}
        </span>
        <button className="btn btn-sm" onClick={() => handleTestOrg(c.id)}>Test</button>
        <button className="btn btn-sm btn-danger" onClick={() => handleDeleteOrg(c.id)}>Delete</button>
      </div>
    ))
  )}
</div>
```

For `OrgConnectorForm`, reuse the page's existing DJ-connector creation form pattern if one exists on this page; otherwise build a minimal form (type select from `TYPE_LABELS`, display name, api key, model hint) that calls `api.createOrgConnector(...)`. Keep it in the same file unless it pushes the file past ~800 lines — then extract `dashboard/app/admin/ai/OrgConnectorSection.tsx`.

4. **Org-default dropdown** (lines ~612-640): change the helper copy to `Connector-less DJs and background jobs use this connector when fallback is allowed.`, and source options from org connectors only:

```tsx
{orgConnectors
  .filter((c) => c.status === 'active')
  .map((c) => (
    <option key={c.id} value={c.id}>
      Organization — {c.display_name} ({TYPE_LABELS[c.connector_type] ?? c.connector_type})
    </option>
  ))}
```

5. **Effective-source badges**: in the per-DJ connectors card, add a small "DJ access" list fed by `api.getDjLlmStatus()`:

```tsx
const SOURCE_LABELS: Record<string, { text: string; color: string }> = {
  own: { text: 'Own connector', color: 'var(--color-success)' },
  org_fallback: { text: 'Org fallback', color: 'var(--color-warning)' },
  none: { text: 'None — AI unavailable', color: 'var(--color-danger)' },
};
```

```tsx
<div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem', marginTop: '1rem' }}>
  {djStatus.map((r) => (
    <div key={r.user_id} style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
      <span style={{ minWidth: 140 }}>{r.username}</span>
      <span style={{ color: SOURCE_LABELS[r.effective_source].color, fontSize: '0.8125rem', fontWeight: 600 }}>
        {SOURCE_LABELS[r.effective_source].text}
      </span>
    </div>
  ))}
</div>
```

6. **Usage rollup**: rows where `dj_username === 'Organization'` already render correctly from the backend label — no change needed beyond confirming.

- [ ] **Step 3: Run tests + type check**

```bash
npx vitest run app/admin/ai --reporter=dot && npx tsc --noEmit
```

Expected: PASS / clean.

- [ ] **Step 4: Commit**

```bash
git add dashboard/app/admin/ai/
git commit -m "feat(admin): org connector section + effective-source badges; drop API Key Status panel"
```

---

### Task 12: DJ-side fallback banner (AiProvidersSection)

**Files:**
- Modify: `dashboard/components/AiProvidersSection.tsx`
- Test: existing tests for the component (grep `AiProvidersSection` under `dashboard/components/__tests__/` or `dashboard/app/(dj)/account/__tests__/`); extend where they live

- [ ] **Step 1: Write the failing test**

In the component's existing test file (or `dashboard/components/__tests__/AiProvidersSection.test.tsx` if none), with the existing `api` mock extended so the policy fetch resolves `org_fallback_available`:

```tsx
it('shows the house-billed banner for a connector-less DJ when fallback is on', async () => {
  vi.mocked(api.listLlmConnectors).mockResolvedValue([]);
  mockPolicy({ org_fallback_available: true });
  render(<AiProvidersSection />);
  await waitFor(() =>
    expect(screen.getByText(/using the organization's connector/i)).toBeInTheDocument(),
  );
});

it('shows the connect-a-provider banner when no fallback exists', async () => {
  vi.mocked(api.listLlmConnectors).mockResolvedValue([]);
  mockPolicy({ org_fallback_available: false });
  render(<AiProvidersSection />);
  await waitFor(() =>
    expect(screen.getByText(/AI features unavailable — connect a provider/i)).toBeInTheDocument(),
  );
});
```

(`mockPolicy` = however the existing tests stub the policy fetch that `fetchPolicySoft()` performs at `AiProvidersSection.tsx:126` — follow the established mock.)

- [ ] **Step 2: Implement the banner**

In `AiProvidersSection.tsx`, replace the bare empty-state (`line ~350: "No connectors yet."`) with:

```tsx
{connectors.length === 0 && !loading && (
  policy?.org_fallback_available ? (
    <div style={{
      background: 'var(--color-warning-subtle)', color: 'var(--color-warning)',
      padding: '0.75rem 1rem', borderRadius: '0.5rem', fontSize: '0.875rem',
    }}>
      You're using the organization's connector — usage is billed to the organization.
      Connect your own provider below to use your own account.
    </div>
  ) : (
    <div style={{
      background: 'var(--color-danger-subtle)', color: 'var(--color-danger)',
      padding: '0.75rem 1rem', borderRadius: '0.5rem', fontSize: '0.875rem',
    }}>
      AI features unavailable — connect a provider below to enable them.
    </div>
  )
)}
```

(The `policy` state already exists from `fetchPolicySoft()`; extend its type with `org_fallback_available`.)

- [ ] **Step 3: Run tests + type check + commit**

```bash
npx vitest run --reporter=dot $(grep -rl "AiProvidersSection" dashboard/components/__tests__ dashboard/app 2>/dev/null | grep test | tr '\n' ' ')
npx tsc --noEmit
git add dashboard/components/ dashboard/app
git commit -m "feat(dashboard): DJ banner — house-billed fallback vs connect-a-provider"
```

---

### Task 13: Full CI + push + PR

- [ ] **Step 1: Backend CI**

```bash
cd /home/adam/github/WrzDJ-worktrees/org-llm/server
$VENV/bin/ruff check . && $VENV/bin/ruff format --check . && $VENV/bin/bandit -r app -c pyproject.toml -q && $VENV/bin/pytest --tb=short -q 2>&1 | tail -5
```

Expected: all clean, coverage ≥ 85%. (Run `$VENV/bin/ruff format .` first if format check fails.)

- [ ] **Step 2: Migration check once more (scratch Postgres, as in Task 2 Step 2)**

- [ ] **Step 3: Frontend CI**

```bash
cd /home/adam/github/WrzDJ-worktrees/org-llm/dashboard
npm run lint && npx tsc --noEmit && npm test -- --run 2>&1 | tail -5
```

- [ ] **Step 4: Push + PR**

```bash
cd /home/adam/github/WrzDJ-worktrees/org-llm
git push -u origin feat/org-llm-connector
gh pr create --title "feat(llm): org-scoped house connector + AI policy clarity" --body "$(cat <<'EOF'
## Summary
Implements docs/superpowers/specs/2026-06-09-admin-ai-policy-design.md:
- Dedicated org-scoped connector (scope column, nullable user_id, CHECK org⇔NULL user)
- llm_enabled rescoped: gates ONLY the org fallback — BYO-connector DJs are never blocked
- Legacy Anthropic env-var surface removed (API Key Status panel, /ai/models, llm_model setting)
- Migration 056 converts the 047-seeded env-var default to org scope; clears personal-connector defaults
- Admin UI: Organization connector card, recopied fallback toggle, per-DJ effective-source badges
- DJ UI: house-billed / connect-a-provider banners

## Test plan
- [ ] Headline regression: BYO DJ dispatch with llm_enabled=False succeeds
- [ ] Org fallback matrix (enabled/disabled × org connector present/absent)
- [ ] Policy PATCH rejects user-scoped defaults
- [ ] alembic upgrade head && alembic check on Postgres
- [ ] Full backend + frontend CI green locally
EOF
)"
```

---

## Self-review notes (already applied)

- Spec §5 named `/settings/ai`; the real DJ connector UI is `AiProvidersSection.tsx` on `/account` — Task 12 targets the real file.
- `AIModelInfo`/`AIModelsResponse` schemas survive because `GET /api/llm/openrouter/models` uses them; only the admin Anthropic listing dies.
- `TrackVibe.llm_model` and `schemas/recommendation.py:llm_model` are telemetry/response fields unrelated to the dropped system setting — explicitly out of scope.
- Existing `test_llm_default_connector.py` seeds user-scoped org defaults; Task 4 Step 4 converts those fixtures to org-scoped rather than deleting coverage.
