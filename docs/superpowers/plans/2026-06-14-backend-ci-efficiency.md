# Backend CI Efficiency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut backend CI runtime by removing repeated test-harness overhead, preserving the enforced coverage gate, and adding safe parallelism only after isolation is fixed.

**Architecture:** Keep production behavior unchanged. Refactor the backend pytest harness so the SQLite schema is created once per test process, each test runs inside an externally managed transaction, normal `TestClient` tests use a no-background app lifespan, and common auth headers are direct JWTs instead of repeated login/bcrypt work. Add permanent pytest duration reporting, then introduce conservative xdist execution.

**Tech Stack:** FastAPI, Starlette `TestClient`, SQLAlchemy 2.x, pytest, pytest-cov, pytest-xdist, SQLite `StaticPool`.

**Branch:** `chore/backend-ci-refactor` in worktree `/home/adam/github/WrzDJ/.worktrees/chore/backend-ci-refactor`. Never edit or commit on `main`.

**Python tooling:** Prefer `/home/adam/github/WrzDJ/server/.venv/bin/{pytest,ruff,bandit,alembic}` from this worktree's `server/` directory if `server/.venv` is absent in the worktree.

---

## File Map

- Modify `.github/workflows/ci.yml`: backend pytest command gets duration output, then xdist once isolation is fixed.
- Modify `server/pyproject.toml`: add `pytest-xdist` to dev dependencies in the final task.
- Modify `server/tests/conftest.py`: transactional DB fixture, test app fixture, direct JWT header helpers, centralized `SessionLocal` patching.
- Modify `server/app/main.py`: add a small app factory and no-background lifespan seam.
- Create `server/tests/test_test_harness.py`: harness regression tests for transaction isolation, auth helper behavior, and direct-session registration.
- Modify `server/tests/test_api.py`: use the no-background app factory explicitly in the global exception handler test.
- Keep auth-specific tests in `server/tests/test_auth.py` and `server/tests/test_auth_jwt_revocation.py` on real login/bcrypt paths.

---

### Task 1: Add Permanent Backend Timing Diagnostics

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the failing command assertion**

Run from repo root:

```bash
rg --fixed-strings "--durations=25 --durations-min=1.0" .github/workflows/ci.yml
```

Expected before the change: no matches and exit code `1`.

- [ ] **Step 2: Update the backend pytest CI command**

In `.github/workflows/ci.yml`, replace the backend test command:

```yaml
        run: pytest --cov=app --cov-report=xml --cov-report=term-missing
```

with:

```yaml
        run: pytest --cov=app --cov-report=xml --cov-report=term-missing --durations=25 --durations-min=1.0
```

- [ ] **Step 3: Verify the assertion passes**

Run:

```bash
rg --fixed-strings "--durations=25 --durations-min=1.0" .github/workflows/ci.yml
git diff --check
```

Expected: `rg` prints the backend pytest command; `git diff --check` prints nothing.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: report slow backend tests" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

---

### Task 2: Replace Per-Test Schema Rebuild With Transaction Rollback

**Files:**
- Modify: `server/tests/conftest.py`
- Create: `server/tests/test_test_harness.py`

- [ ] **Step 1: Write harness regression tests**

Create `server/tests/test_test_harness.py`:

```python
"""Regression tests for backend pytest harness behavior."""

from sqlalchemy.orm import Session

from app.models.user import User


def test_db_fixture_uses_external_transaction(db: Session):
    """The harness should bind each Session to a transaction-owned Connection."""
    bind = db.get_bind()
    assert hasattr(bind, "in_transaction")
    assert bind.in_transaction() is True
    assert db.join_transaction_mode == "create_savepoint"


def test_committed_rows_are_visible_within_current_test(db: Session):
    user = User(username="transaction_probe", password_hash="x", role="dj")
    db.add(user)
    db.commit()

    assert db.query(User).filter(User.username == "transaction_probe").count() == 1


def test_committed_rows_are_rolled_back_between_tests(db: Session):
    assert db.query(User).filter(User.username == "transaction_probe").count() == 0
```

- [ ] **Step 2: Run the new harness tests and verify the first one fails**

Run:

```bash
cd server
/home/adam/github/WrzDJ/server/.venv/bin/pytest tests/test_test_harness.py -q --no-cov
```

Expected before the fixture refactor: `test_db_fixture_uses_external_transaction` fails because the existing fixture is not using `join_transaction_mode == "create_savepoint"`.

- [ ] **Step 3: Refactor the DB setup in `conftest.py`**

Replace the top-level sessionmaker and `db` fixture in `server/tests/conftest.py` with this structure. Keep the existing model fixture definitions below it.

```python
from collections.abc import Generator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import sse as _sse_module
from app.api.deps import get_db
import app.db.session as _db_session_module
from app.core.time import utcnow
from app.main import app
from app.models.base import Base
from app.models.event import Event
from app.models.guest import Guest
from app.models.request import Request, RequestStatus
from app.models.user import User

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@pytest.fixture(scope="session", autouse=True)
def _database_schema() -> Generator[None, None, None]:
    """Create the in-memory SQLite schema once per pytest process."""
    Base.metadata.create_all(bind=engine)
    try:
        yield
    finally:
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db(monkeypatch: pytest.MonkeyPatch, _database_schema: None) -> Generator[Session, None, None]:
    """Run each test inside an externally managed transaction.

    Application code may call Session.commit(); SQLAlchemy keeps those commits
    inside a SAVEPOINT while this fixture rolls back the outer transaction.
    """
    connection = engine.connect()
    transaction = connection.begin()
    TestSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=connection,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(_db_session_module, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(_sse_module, "SessionLocal", TestSessionLocal, raising=False)

    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
```

After adding this, remove the old top-level `TestingSessionLocal` and the old `_sse_module.SessionLocal = TestingSessionLocal` assignment. Later tasks will add back auth helpers and the test app fixture.

- [ ] **Step 4: Run the harness tests**

Run:

```bash
cd server
/home/adam/github/WrzDJ/server/.venv/bin/pytest tests/test_test_harness.py -q --no-cov
```

Expected: all three tests pass.

- [ ] **Step 5: Run representative DB-heavy tests**

Run:

```bash
cd server
/home/adam/github/WrzDJ/server/.venv/bin/pytest tests/test_voting.py tests/test_collect_service.py tests/test_llm_call_log_retention.py -q --no-cov
```

Expected: pass. If a test depended on cross-test state, fix that test by creating its own setup data.

- [ ] **Step 6: Commit**

```bash
git add server/tests/conftest.py server/tests/test_test_harness.py
git commit -m "test: isolate database tests with transactions" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

---

### Task 3: Add a No-Background Test Lifespan

**Files:**
- Modify: `server/app/main.py`
- Modify: `server/tests/conftest.py`
- Modify: `server/tests/test_api.py`
- Modify: `server/tests/test_test_harness.py`

- [ ] **Step 1: Add failing tests for app factory behavior**

Append to `server/tests/test_test_harness.py`:

```python
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app, no_background_lifespan


def test_no_background_test_client_skips_lifespan_tasks():
    with (
        patch("app.main._tidal_collection_poll_loop") as tidal_loop,
        patch("app.main._llm_call_log_cleanup_loop") as cleanup_loop,
        patch("app.services.llm.health_monitor.health_monitor_loop") as health_loop,
    ):
        test_app = create_app(lifespan_context=no_background_lifespan)
        with TestClient(test_app) as client:
            assert client.get("/health").status_code == 200

    tidal_loop.assert_not_called()
    cleanup_loop.assert_not_called()
    health_loop.assert_not_called()


def test_real_lifespan_starts_and_cancels_background_tasks():
    async def neverending():
        import asyncio

        await asyncio.Event().wait()

    with (
        patch("app.main._tidal_collection_poll_loop", side_effect=neverending) as tidal_loop,
        patch("app.main._llm_call_log_cleanup_loop", side_effect=neverending) as cleanup_loop,
        patch("app.services.llm.health_monitor.health_monitor_loop", side_effect=neverending)
        as health_loop,
    ):
        real_app = create_app()
        with TestClient(real_app) as client:
            assert client.get("/health").status_code == 200

    tidal_loop.assert_called_once()
    cleanup_loop.assert_called_once()
    health_loop.assert_called_once()
```

- [ ] **Step 2: Run the tests and verify import failure**

Run:

```bash
cd server
/home/adam/github/WrzDJ/server/.venv/bin/pytest tests/test_test_harness.py::test_no_background_test_client_skips_lifespan_tasks -q --no-cov
```

Expected before implementation: import error for `create_app` or `no_background_lifespan`.

- [ ] **Step 3: Refactor `server/app/main.py` into a small factory**

Keep the existing cleanup/poll functions unchanged. Move `global_exception_handler` above `create_app()`, then replace the current `lifespan`, global `app = FastAPI(...)`, middleware registration, router include, upload mount, and `@app.get("/health")` block with this structure:

```python
@asynccontextmanager
async def lifespan(app: FastAPI, *, run_background_tasks: bool = True):
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True

    tasks: list[asyncio.Task] = []
    if run_background_tasks:
        from app.services.llm.health_monitor import health_monitor_loop

        tasks = [
            asyncio.create_task(_tidal_collection_poll_loop()),
            asyncio.create_task(_llm_call_log_cleanup_loop()),
            asyncio.create_task(health_monitor_loop()),
        ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task


@asynccontextmanager
async def no_background_lifespan(app: FastAPI):
    async with lifespan(app, run_background_tasks=False):
        yield


def create_app(*, lifespan_context=lifespan) -> FastAPI:
    application = FastAPI(
        title="WrzDJ API",
        description="Song request system for DJs",
        version="0.1.0",
        lifespan=lifespan_context,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    application.state.limiter = limiter
    application.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    application.add_exception_handler(Exception, global_exception_handler)
    application.add_middleware(SecurityHeadersMiddleware)

    if settings.cors_origins.strip() == "*":
        application.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        origins = [origin.strip() for origin in settings.cors_origins.split(",")]
        application.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=CORS_ALLOW_METHODS,
            allow_headers=["Authorization", "Content-Type", "X-Kiosk-Session"],
            expose_headers=["Content-Disposition"],
        )

    application.include_router(api_router, prefix="/api")

    uploads_dir = Path(settings.resolved_uploads_dir)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    application.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

    @application.get("/health")
    def health_check():
        return {"status": "ok"}

    return application


app = create_app()
```

Leave `global_exception_handler` as a top-level function. Remove the old `@app.exception_handler(Exception)` decorator and register it inside `create_app()` as shown.

- [ ] **Step 4: Use the no-background app in `conftest.py`**

Change the import:

```python
from app.main import app
```

to:

```python
from app.main import create_app, no_background_lifespan
```

Add this fixture above `client`:

```python
@pytest.fixture(scope="session")
def test_app():
    """FastAPI app instance for tests; lifespan runs without production loops."""
    return create_app(lifespan_context=no_background_lifespan)
```

Change the `client` fixture to accept and use `test_app`:

```python
@pytest.fixture(scope="function")
def client(db: Session, test_app) -> Generator[TestClient, None, None]:
    """Create a test client with database override."""

    def override_get_db():
        try:
            yield db
        finally:
            pass

    test_app.dependency_overrides[get_db] = override_get_db
    with TestClient(test_app) as c:
        yield c
    test_app.dependency_overrides.clear()
```

- [ ] **Step 5: Update the explicit exception-handler test**

In `server/tests/test_api.py`, replace the local import and client construction in `test_global_exception_handler_returns_500`:

```python
    from app.main import app
```

with:

```python
    from app.main import create_app, no_background_lifespan

    test_app = create_app(lifespan_context=no_background_lifespan)
```

and replace:

```python
        with TestClient(app, raise_server_exceptions=False) as c:
```

with:

```python
        with TestClient(test_app, raise_server_exceptions=False) as c:
```

- [ ] **Step 6: Run lifespan and API tests**

Run:

```bash
cd server
/home/adam/github/WrzDJ/server/.venv/bin/pytest tests/test_test_harness.py tests/test_api.py -q --no-cov
```

Expected: pass. If the real-lifespan test hangs, replace the `neverending()` helper with an async function that awaits `asyncio.sleep(3600)`; cancellation during `TestClient` teardown should still exit the context promptly.

- [ ] **Step 7: Commit**

```bash
git add server/app/main.py server/tests/conftest.py server/tests/test_api.py server/tests/test_test_harness.py
git commit -m "test: skip production background loops in client fixture" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

---

### Task 4: Replace Common Auth Fixture Login With Direct JWT Headers

**Files:**
- Modify: `server/tests/conftest.py`
- Modify: `server/tests/test_test_harness.py`

- [ ] **Step 1: Add tests for the direct-token helper**

Append to `server/tests/test_test_harness.py`:

```python
from app.services.auth import decode_token
from conftest import _auth_headers_for_user


def test_auth_headers_for_user_builds_valid_token(test_user: User):
    headers = _auth_headers_for_user(test_user)
    token = headers["Authorization"].removeprefix("Bearer ")

    token_data = decode_token(token)

    assert token_data is not None
    assert token_data.username == "testuser"
    assert token_data.token_version == test_user.token_version
```

- [ ] **Step 2: Run the helper test and verify import failure**

Run:

```bash
cd server
/home/adam/github/WrzDJ/server/.venv/bin/pytest tests/test_test_harness.py::test_auth_headers_for_user_builds_valid_token -q --no-cov
```

Expected before implementation: import error for `_auth_headers_for_user`.

- [ ] **Step 3: Add fast bcrypt constants and a direct header helper**

In `server/tests/conftest.py`, update the common fixtures to use precomputed low-round hashes. Do not import `get_password_hash` in `conftest.py`; auth-specific test modules import it themselves when they need to exercise real hashing.

Add this import near the other service imports:

```python
from app.services.auth import create_access_token
```

Add near the engine definition:

```python
TEST_USER_PASSWORD = "testpassword123"
ADMIN_USER_PASSWORD = "adminpassword123"
PENDING_USER_PASSWORD = "pendingpassword123"

TEST_USER_PASSWORD_HASH = "$2b$04$BIUR.p93nOe8nGJXBjtYhu6QLsv7BHn22sAfR/Tpt6xMdl9tEf4tS"
ADMIN_USER_PASSWORD_HASH = "$2b$04$LaJfWm6YwkBoEVVFvnxu7unVKG7HRGM9hiSvk448HhWZK.hPijb7a"
PENDING_USER_PASSWORD_HASH = "$2b$04$BnvACwtrVGvZhu5TzYdOR.tpGyY6OQ4p5oILNEgHPmvOGWotCWWYu"


def _auth_headers_for_user(user: User) -> dict[str, str]:
    token = create_access_token(data={"sub": user.username, "tv": user.token_version})
    return {"Authorization": f"Bearer {token}"}
```

Change `test_user`, `admin_user`, and `pending_user` to use the constants:

```python
password_hash=TEST_USER_PASSWORD_HASH
password_hash=ADMIN_USER_PASSWORD_HASH
password_hash=PENDING_USER_PASSWORD_HASH
```

Change `auth_headers`, `admin_headers`, and `pending_headers` to remove `client` from their signatures and return direct tokens:

```python
@pytest.fixture
def admin_headers(admin_user: User) -> dict[str, str]:
    """Authentication headers for the admin user without exercising login."""
    return _auth_headers_for_user(admin_user)


@pytest.fixture
def pending_headers(pending_user: User) -> dict[str, str]:
    """Authentication headers for the pending user without exercising login."""
    return _auth_headers_for_user(pending_user)


@pytest.fixture
def auth_headers(test_user: User) -> dict[str, str]:
    """Authentication headers for the DJ user without exercising login."""
    return _auth_headers_for_user(test_user)
```

- [ ] **Step 4: Run auth-focused tests that must still use real login**

Run:

```bash
cd server
/home/adam/github/WrzDJ/server/.venv/bin/pytest tests/test_auth.py tests/test_auth_jwt_revocation.py tests/test_api_contracts.py::TestAuthContracts::test_login_response_shape -q --no-cov
```

Expected: pass. These tests still call `/api/auth/login`, and the low-round bcrypt hashes must verify the documented passwords.

- [ ] **Step 5: Run representative authenticated endpoint tests**

Run:

```bash
cd server
/home/adam/github/WrzDJ/server/.venv/bin/pytest tests/test_events.py::TestCreateEvent::test_create_event_success tests/test_admin.py::TestAdminUserManagement::test_list_users tests/test_setbuilder_api.py -q --no-cov
```

Expected: pass. If a selected node name has changed, run the whole listed file with `-q --no-cov` and keep the failure output for the implementation notes.

- [ ] **Step 6: Commit**

```bash
git add server/tests/conftest.py server/tests/test_test_harness.py
git commit -m "test: build auth fixture headers directly" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

---

### Task 5: Centralize Direct `SessionLocal` Test Routing

**Files:**
- Modify: `server/tests/conftest.py`
- Modify: `server/tests/test_test_harness.py`
- Modify: `server/tests/test_llm_call_log_retention.py`
- Modify: `server/tests/test_sse_pool.py` if its local patch duplicates the centralized fixture after this change

- [ ] **Step 1: Add a registration guard test**

Append to `server/tests/test_test_harness.py`:

```python
from conftest import DIRECT_SESSIONLOCAL_MODULES


def test_direct_sessionlocal_module_aliases_are_registered():
    module_names = {module.__name__ for module in DIRECT_SESSIONLOCAL_MODULES}

    assert "app.api.sse" in module_names
```

- [ ] **Step 2: Run the guard and verify import failure**

Run:

```bash
cd server
/home/adam/github/WrzDJ/server/.venv/bin/pytest tests/test_test_harness.py::test_direct_sessionlocal_module_aliases_are_registered -q --no-cov
```

Expected before implementation: import error for `DIRECT_SESSIONLOCAL_MODULES`.

- [ ] **Step 3: Define the centralized patch list in `conftest.py`**

Add near the imports in `server/tests/conftest.py`:

```python
DIRECT_SESSIONLOCAL_MODULES = (_sse_module,)
```

Change the `db` fixture patching block from:

```python
    monkeypatch.setattr(_db_session_module, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(_sse_module, "SessionLocal", TestSessionLocal, raising=False)
```

to:

```python
    monkeypatch.setattr(_db_session_module, "SessionLocal", TestSessionLocal)
    for module in DIRECT_SESSIONLOCAL_MODULES:
        monkeypatch.setattr(module, "SessionLocal", TestSessionLocal, raising=False)
```

- [ ] **Step 4: Remove duplicate per-test SessionLocal monkeypatching where safe**

In `server/tests/test_llm_call_log_retention.py`, remove the two repeated lines that set `app.db.session.SessionLocal` to `lambda: db` and monkeypatch `db.close`. The centralized fixture now points lazy imports at a session factory bound to the test transaction.

The test bodies should call `main_module._run_llm_call_log_cleanup()` directly:

```python
        import app.main as main_module

        main_module._run_llm_call_log_cleanup()
```

If `server/tests/test_sse_pool.py` patches `app.api.sse.SessionLocal` only to avoid real Postgres, remove that local patch. Keep any patch that is explicitly testing pool behavior or stream lifetime behavior.

- [ ] **Step 5: Run direct-session tests**

Run:

```bash
cd server
/home/adam/github/WrzDJ/server/.venv/bin/pytest tests/test_llm_call_log_retention.py tests/test_sse_pool.py tests/test_sse_security.py tests/test_test_harness.py -q --no-cov
```

Expected: pass. If cleanup closes a short-lived direct session, it must not close the primary `db` fixture session because the direct session should be a separate `TestSessionLocal()` instance on the same connection.

- [ ] **Step 6: Commit**

```bash
git add server/tests/conftest.py server/tests/test_test_harness.py server/tests/test_llm_call_log_retention.py server/tests/test_sse_pool.py
git commit -m "test: centralize direct session routing" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

If `server/tests/test_sse_pool.py` did not need edits, omit it from `git add`.

---

### Task 6: Add Conservative xdist Execution

**Files:**
- Modify: `server/pyproject.toml`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add `pytest-xdist` to dev dependencies**

In `server/pyproject.toml`, add this line to `[project.optional-dependencies].dev` next to the pytest entries:

```toml
    "pytest-xdist>=3.6.0",
```

- [ ] **Step 2: Update CI pytest command**

In `.github/workflows/ci.yml`, change the backend test command from:

```yaml
        run: pytest --cov=app --cov-report=xml --cov-report=term-missing --durations=25 --durations-min=1.0
```

to:

```yaml
        run: pytest -n 4 --dist=loadfile --cov=app --cov-report=xml --cov-report=term-missing --durations=25 --durations-min=1.0
```

Use `--dist=loadfile` so tests in the same file stay on the same worker, reducing fixture churn and keeping file-local isolation checks meaningful.

- [ ] **Step 3: Run a local two-worker smoke**

Run:

```bash
cd server
/home/adam/github/WrzDJ/server/.venv/bin/pytest -n 2 --dist=loadfile tests/test_test_harness.py tests/test_api.py tests/test_auth.py -q --no-cov
```

Expected: pass. If `pytest-xdist` is not installed in the local shared venv, run the command after `pip install -e ".[dev]"` from `server/` or let CI install it through the updated dev extra.

- [ ] **Step 4: Run full backend tests with coverage**

Run:

```bash
cd server
/home/adam/github/WrzDJ/server/.venv/bin/pytest -n 4 --dist=loadfile --cov=app --cov-report=term-missing --cov-branch --cov-fail-under=85 --durations=25 --durations-min=1.0 --tb=short -q
```

Expected: pass with coverage at or above 85%. Capture the final runtime and the slowest-test report for the PR body.

- [ ] **Step 5: Commit**

```bash
git add server/pyproject.toml .github/workflows/ci.yml
git commit -m "ci: run backend tests with xdist" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

---

### Task 7: Final Verification and PR Notes

**Files:**
- No required file edits unless verification finds a defect.

- [ ] **Step 1: Run backend lint, format, security, and tests**

Run:

```bash
cd server
/home/adam/github/WrzDJ/server/.venv/bin/ruff check .
/home/adam/github/WrzDJ/server/.venv/bin/ruff format --check .
/home/adam/github/WrzDJ/server/.venv/bin/bandit -r app -c pyproject.toml -q
/home/adam/github/WrzDJ/server/.venv/bin/pytest -n 4 --dist=loadfile --cov=app --cov-report=term-missing --cov-branch --cov-fail-under=85 --durations=25 --durations-min=1.0 --tb=short -q
/home/adam/github/WrzDJ/server/.venv/bin/alembic upgrade head
/home/adam/github/WrzDJ/server/.venv/bin/alembic check
```

Expected: all commands pass. Coverage remains at or above 85%.

- [ ] **Step 2: Inspect branch diff**

Run:

```bash
git status --short
git diff origin/main...HEAD --stat
git diff origin/main...HEAD -- server/tests/conftest.py server/app/main.py .github/workflows/ci.yml server/pyproject.toml
```

Expected: only backend CI/test-harness changes plus the approved spec/plan docs.

- [ ] **Step 3: Record PR testing notes**

Use this testing section in the PR body and fill the runtime from the full pytest command:

```markdown
## Testing
- [ ] Backend lint: `ruff check .`
- [ ] Backend format: `ruff format --check .`
- [ ] Backend security: `bandit -r app -c pyproject.toml -q`
- [ ] Backend tests: `pytest -n 4 --dist=loadfile --cov=app --cov-report=term-missing --cov-branch --cov-fail-under=85 --durations=25 --durations-min=1.0 --tb=short -q` (<runtime>)
- [ ] Alembic: `alembic upgrade head && alembic check`
```

No commit is needed for this task unless a verification fix changes files.
