# Backend CI Efficiency - Design

**Date:** 2026-06-14
**Author:** thewrz (design session with Codex)
**Branch:** `chore/backend-ci-refactor`
**Status:** Approved design, pending implementation plan

## Problem

The backend PR gate is too slow for routine development. The motivating CI run spent
13m11s inside "Run tests with coverage"; install, lint, and security checks were small
by comparison. The suite collects roughly 2,800 tests, so the main issue is runtime
overhead repeated across many tests, not collection.

Current harness hot spots:

- `server/tests/conftest.py` rebuilds all SQLAlchemy tables for every `db` test via
  `Base.metadata.create_all()` and `drop_all()`.
- `client` creates `TestClient(app)` as a context manager for every client test, which
  starts the app lifespan and launches production background loops.
- Common auth fixtures create real bcrypt hashes and then log in through `/api/auth/login`.
- A few production paths intentionally bypass FastAPI `get_db` and open `SessionLocal()`
  directly; in tests this can hit CI Postgres instead of the SQLite test database unless
  each bypass is patched.
- CI has no durable slow-test timings and no xdist parallelism.

## Goals

- Move backend CI toward a practical PR-gate target of 3-6 minutes without lowering the
  enforced coverage gate.
- Preserve the current test surface and behavior coverage where it is meaningful.
- Make test isolation stronger before adding parallelism.
- Keep production app behavior unchanged.
- Leave a permanent timing signal in CI so future regressions are visible.

## Non-goals

- Lowering `--cov-fail-under=85` or removing branch coverage.
- Rewriting broad endpoint matrices into service tests in this PR.
- Migrating backend tests from SQLite to PostgreSQL.
- Changing production password hashing strength.
- Disabling the Alembic drift check.

## Decisions

| Question | Decision |
|---|---|
| First-order fix | Refactor the backend test harness, not the product code |
| Database isolation | Create schema once per pytest session; isolate each test with an outer transaction rollback |
| HTTP client behavior | Keep `client` function-scoped, but default it to a no-background test lifespan |
| Auth fixture path | Generate JWT headers directly for common fixtures; keep real login/bcrypt tests where auth is under test |
| Direct `SessionLocal()` paths | Centralize test patching so intentional bypasses use the test session factory |
| Parallelism | Add xdist only after transaction/lifespan/global-state isolation is stable |
| Measurement | Add `--durations=25 --durations-min=1.0` to backend CI pytest |

## 1. Database fixture

Replace the per-test schema rebuild with a session-level schema fixture plus a
function-level transaction fixture.

Target shape:

- `Base.metadata.create_all(bind=engine)` runs once for the pytest session.
- Each `db` fixture opens a connection, begins an outer transaction, and binds a
  `Session` to that connection.
- Test code may call `db.commit()` normally.
- Teardown closes the session and rolls back the outer transaction, returning the database
  to a clean state without dropping tables.
- `Base.metadata.drop_all(bind=engine)` runs once at session teardown.

This follows SQLAlchemy's documented "join into an external transaction" test recipe.
SQLAlchemy 2.x specifically supports binding a session to an externally managed
transaction so application code can call `Session.commit()` while the test harness rolls
the whole interaction back afterward.

Implementation details to verify during planning:

- Use SQLAlchemy 2.x's supported `join_transaction_mode` if available in the installed
  version; otherwise use the documented compatible pattern for the local dependency floor.
- Keep SQLite `StaticPool` so the in-memory database survives across connections for the
  process.
- Add a harness regression test that inserts and commits data in one test, then proves the
  next test starts clean.
- Audit tests that depend on table DDL side effects, raw connection state, or cross-test
  persistence. Those should be rewritten; cross-test persistence is a test bug.

## 2. App lifespan and background loops

Normal endpoint tests should not start production background loops. The current `client`
fixture uses `TestClient(app)` as a context manager, and Starlette documents that lifespan
handlers run when `TestClient` is used that way.

Design:

- Introduce a test-mode app lifespan path that skips:
  - Tidal collection polling loop.
  - LLM call-log cleanup loop.
  - LLM health monitor loop.
- Keep a small dedicated lifespan test set that exercises the real lifespan and task
  cancellation behavior explicitly.
- Preserve per-test `TestClient` instance isolation for cookies, headers, and app
  dependency overrides.

Preferred implementation is a small app-factory or lifespan-factory seam in
`server/app/main.py`, not monkeypatching `asyncio.create_task` globally. The production
`app` object should still be created with the real lifespan by default; tests can opt into
the no-background app instance or no-background lifespan.

## 3. Auth fixture fast path

Most endpoint tests need "a valid DJ/admin/pending request", not a bcrypt/login integration
test. Common fixtures should create users in the database and then build headers directly
with `create_access_token(data={"sub": user.username, "tv": user.token_version})`.

Keep real bcrypt and login coverage in:

- `/api/auth/login` success and failure tests.
- JWT token-version and logout/revocation tests where fresh login behavior is under test.
- Lockout and timing-equalization tests.
- Password policy/hash tests.

For fixture users:

- Use a precomputed valid bcrypt hash constant or a test helper that avoids repeated
  expensive hashing where the password is never checked.
- Keep password hash format realistic enough that accidental login use still fails loudly
  or is covered by auth-specific tests.
- Document the helper so new tests choose direct token headers unless they are explicitly
  testing login.

## 4. Direct SessionLocal bypasses

Some production code deliberately opens fresh sessions to avoid long-lived request session
problems, notably SSE existence checks, background enrichment/sync helpers, and LLM cleanup
or health-monitor paths. That is legitimate production design, but the test harness must
ensure those paths do not talk to CI Postgres during SQLite tests.

Design:

- Centralize test-session patching in `conftest.py` instead of one-off patches.
- Patch known direct imports that bypass `get_db`, including:
  - `app.api.sse.SessionLocal`.
  - `app.db.session.SessionLocal` for code that imports it lazily inside functions.
  - Any module-level `SessionLocal` aliases found during implementation.
- Add a guard test or lightweight audit helper that fails if a new direct `SessionLocal`
  use is added without an explicit test-harness decision.

This should preserve production's pool-safety decisions while making test database routing
obvious and enforceable.

## 5. Timing diagnostics

Add durable timing output to backend CI:

```bash
pytest --cov=app --cov-report=xml --cov-report=term-missing --durations=25 --durations-min=1.0
```

Keep the local default `addopts` coverage gate intact. This gives reviewers a recurring list
of slow tests after each CI run without adding a new dependency.

## 6. Parallel test execution

After the harness is isolated, add `pytest-xdist` conservatively:

- Add `pytest-xdist` to `server/pyproject.toml` dev dependencies.
- Start CI with a fixed worker count such as `-n 2` or `-n 4`, not necessarily `-n auto`,
  to avoid oversubscribing GitHub-hosted runners.
- Keep pytest-cov as the coverage driver; pytest-cov supports xdist coverage combination.
- If order/global-state failures appear, fix the isolation problem rather than pinning test
  order.

Do not land xdist before the transaction and lifespan fixes are passing. xdist runs separate
worker processes, so session-scoped fixtures execute once per worker, not once for the whole
job. The DB setup must be cheap and worker-safe before this is useful.

## 7. Testing

Backend focused checks:

- Harness regression: committed rows are visible within a test but absent in the next test.
- Endpoint smoke: representative `client + db + auth_headers` tests still pass with direct
  token headers and no background lifespan tasks.
- Auth coverage: login success/failure still exercises bcrypt and password verification.
- Lifespan coverage: a dedicated test still invokes the real lifespan and verifies tasks are
  started and cancelled.
- Direct-session coverage: SSE and cleanup/monitor paths use the test database under pytest.
- CI command coverage: `pytest --cov=app --cov-report=xml --cov-report=term-missing
  --durations=25 --durations-min=1.0`.

Full local checks before PR:

```bash
cd server
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/bandit -r app -c pyproject.toml -q
.venv/bin/pytest --tb=short -q
.venv/bin/alembic upgrade head && .venv/bin/alembic check
```

## Rollout

Recommended implementation sequence:

1. Add timing diagnostics to CI so subsequent commits expose runtime deltas.
2. Introduce the session-level schema and transactional `db` fixture with harness
   regression tests.
3. Add no-background test lifespan/client behavior and dedicated real-lifespan tests.
4. Convert common auth headers to direct token construction while preserving auth endpoint
   tests.
5. Centralize direct `SessionLocal` test routing and add a guard.
6. Run the full backend suite and inspect durations.
7. Add xdist only after the suite is isolated and green.

This can land as one larger PR, but the commits should be reviewable in the sequence above.

## Risk register

| Risk | Mitigation |
|---|---|
| Transaction fixture breaks tests that rely on cross-test state | Treat as a test isolation bug; add explicit setup in those tests |
| `db.commit()` escapes the rollback boundary | Use SQLAlchemy's documented external-transaction recipe and pin it with a regression test |
| SQLite DDL or connection behavior differs under session-scoped schema | Keep schema DDL outside individual tests; audit any test that performs DDL |
| No-background client hides startup bugs | Keep dedicated real-lifespan tests and do not remove production lifespan coverage |
| Direct token headers skip auth behavior too broadly | Restrict real login tests to auth-specific files and document fixture intent |
| xdist exposes order/global-state flakes | Add xdist after isolation fixes; fix state leaks rather than marking tests serial by default |
| In-memory SQLite under xdist creates one DB per worker | Acceptable; each worker has isolated process-local DB and combined coverage |

## Sources

- SQLAlchemy documentation, "Joining a Session into an External Transaction" in
  Transactions and Connection Management:
  https://docs.sqlalchemy.org/en/latest/orm/session_transaction.html
- Starlette TestClient documentation on lifespan behavior:
  https://starlette.dev/testclient/
- pytest documentation on `--durations` and `--durations-min`:
  https://docs.pytest.org/en/stable/how-to/usage.html
- pytest-cov documentation on xdist coverage support:
  https://pytest-cov.readthedocs.io/en/latest/xdist.html
- pytest-xdist documentation on session-scoped fixtures executing once per worker:
  https://pytest-xdist.readthedocs.io/en/stable/how-to.html
