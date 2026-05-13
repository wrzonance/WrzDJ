# Admin UI Fixes & Persistent API Logs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix misleading admin toggle label for bot protection, and make API logs persist to a host-mounted directory across container restarts.

**Architecture:** Part A is a two-string frontend change. Part B extracts a `configure_logging()` function to `app/core/logging_config.py`, wires it into `main.py`, and adds a bind-mount volume in the deploy compose file — no new services.

**Tech Stack:** Next.js (Part A); Python `logging` stdlib + `python-json-logger`, FastAPI lifespan, Docker Compose bind-mount (Part B).

---

## Branch

- [ ] **Create feature branch**

```bash
git checkout -b fix/admin-toggle-text-and-persistent-logs
```

---

## Task 1: Fix Admin Toggle Label and Description

**Files:**
- Modify: `dashboard/app/admin/settings/page.tsx:99-101`

- [ ] **Step 1: Apply the two string changes**

In `dashboard/app/admin/settings/page.tsx`, change lines 99–101:

```tsx
// Before:
<div style={{ fontWeight: 500 }}>Enforce human verification on guest pages</div>
<div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
  When ON, guests must complete a Cloudflare Turnstile check before submitting requests, voting, or searching. Default OFF (soft mode logs warnings only).
</div>

// After:
<div style={{ fontWeight: 500 }}>Enforce bot protection on guest pages</div>
<div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
  Cloudflare Turnstile runs silently for all guests — most see no challenge. When ON, guests who fail the check are blocked from submitting requests, voting, or searching. When OFF, failures are only logged.
</div>
```

- [ ] **Step 2: Type-check**

```bash
cd dashboard && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add dashboard/app/admin/settings/page.tsx
git commit -m "fix(admin): correct bot protection toggle label and description"
```

---

## Task 2: Add python-json-logger Dependency

**Files:**
- Modify: `server/pyproject.toml`

- [ ] **Step 1: Add to dependencies**

In `server/pyproject.toml`, add `"python-json-logger>=3.0"` to the `[project.dependencies]` list (after the `sse-starlette` line):

```toml
dependencies = [
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "sqlalchemy>=2.0.0",
    "alembic>=1.13.0",
    "psycopg[binary]>=3.1.0",
    "pydantic[email]>=2.0.0",
    "pydantic-settings>=2.0.0",
    "bcrypt>=4.0.0",
    "httpx>=0.26.0",
    "python-multipart>=0.0.27",
    "spotipy>=2.23.0",
    "slowapi>=0.1.9",
    "tidalapi>=0.7.0",
    "Pillow>=12.1.1",
    "cryptography>=46.0.7",
    "PyJWT>=2.12.0",
    "aiohttp>=3.13.4",
    "requests>=2.33.0",
    "python-dotenv>=1.2.2",
    "mako>=1.3.12",
    "pyasn1>=0.6.3",
    "anthropic>=0.40.0",
    "resend>=2.0.0",
    "better-profanity>=0.7.0",
    "sse-starlette>=2.0.0",
    "python-json-logger>=3.0",
]
```

- [ ] **Step 2: Install into venv**

```bash
cd server && .venv/bin/pip install -e ".[dev]"
```

Expected: `Successfully installed python-json-logger-3.x.x` (or `Requirement already satisfied` if cached).

- [ ] **Step 3: Verify import works**

```bash
cd server && .venv/bin/python -c "from pythonjsonlogger.jsonlogger import JsonFormatter; print('ok')"
```

Expected: `ok`

---

## Task 3: Implement configure_logging() — TDD

**Files:**
- Create: `server/tests/test_logging_config.py`
- Create: `server/app/core/logging_config.py`

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_logging_config.py`:

```python
import logging
import logging.handlers

import pytest


def _reset_root_logger(original_handlers, original_level):
    root = logging.getLogger()
    for h in root.handlers:
        h.close()
    root.handlers = original_handlers
    root.level = original_level


@pytest.fixture()
def clean_root_logger():
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    root.handlers.clear()
    yield
    _reset_root_logger(original_handlers, original_level)


def test_no_file_handler_without_log_dir(clean_root_logger, monkeypatch):
    monkeypatch.delenv("LOG_DIR", raising=False)
    from app.core.logging_config import configure_logging

    configure_logging()

    root = logging.getLogger()
    handler_types = [type(h) for h in root.handlers]
    assert logging.StreamHandler in handler_types
    assert logging.handlers.RotatingFileHandler not in handler_types


def test_file_handler_created_with_log_dir(clean_root_logger, tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    from app.core.logging_config import configure_logging

    configure_logging()

    root = logging.getLogger()
    file_handlers = [
        h for h in root.handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    assert file_handlers[0].baseFilename == str(tmp_path / "app.log")
    assert file_handlers[0].maxBytes == 10 * 1024 * 1024
    assert file_handlers[0].backupCount == 5


def test_log_message_written_to_file(clean_root_logger, tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    from app.core.logging_config import configure_logging

    configure_logging()
    logging.getLogger("app.logging_config_test").info("hello persistent logs")

    log_file = tmp_path / "app.log"
    assert log_file.exists()
    assert "hello persistent logs" in log_file.read_text()


def test_root_logger_level_set_to_info(clean_root_logger, monkeypatch):
    monkeypatch.delenv("LOG_DIR", raising=False)
    from app.core.logging_config import configure_logging

    configure_logging()

    assert logging.getLogger().level == logging.INFO
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd server && .venv/bin/pytest tests/test_logging_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.core.logging_config'`

- [ ] **Step 3: Implement configure_logging()**

Create `server/app/core/logging_config.py`:

```python
import logging
import logging.handlers
import os


def configure_logging() -> None:
    """Install dual-handler logging on the root logger.

    File handler (plain text, rotating) is added only when LOG_DIR env var is set.
    Stream handler (JSON) is always active.

    Call once at application startup before any loggers emit messages.
    """
    from pythonjsonlogger.jsonlogger import JsonFormatter

    log_dir = os.environ.get("LOG_DIR", "")

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(
        JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root.addHandler(stream_handler)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, "app.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        root.addHandler(file_handler)
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd server && .venv/bin/pytest tests/test_logging_config.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add server/tests/test_logging_config.py server/app/core/logging_config.py server/pyproject.toml
git commit -m "feat(logging): add configure_logging() with dual-handler output"
```

---

## Task 4: Wire configure_logging() into main.py

**Files:**
- Modify: `server/app/main.py:25-28` (replace one-liner)
- Modify: `server/app/main.py:72-80` (update lifespan)

- [ ] **Step 1: Replace the one-liner logging setup**

In `server/app/main.py`, replace lines 25–28:

```python
# Before:
# Configure app-level logging so module loggers (enrichment, sync, etc.)
# emit INFO-level diagnostics instead of being silenced by Python's default WARNING level.
logging.getLogger("app").setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# After:
from app.core.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)
```

- [ ] **Step 2: Add uvicorn logger reconfiguration to lifespan**

In `server/app/main.py`, update the `lifespan` context manager to reconfigure uvicorn loggers at startup (uvicorn installs its own handlers after the module is imported, so this must run inside lifespan):

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    task = asyncio.create_task(_tidal_collection_poll_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
```

- [ ] **Step 3: Run full backend test suite**

```bash
cd server && .venv/bin/pytest --tb=short -q
```

Expected: all tests pass, no import errors.

- [ ] **Step 4: Run lint and format check**

```bash
cd server && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: no errors. If format errors: `cd server && .venv/bin/ruff format .` then re-check.

- [ ] **Step 5: Commit**

```bash
git add server/app/main.py
git commit -m "feat(logging): wire configure_logging into main.py and lifespan"
```

---

## Task 5: Deploy Config — Volume Mount and Log Directory

**Files:**
- Modify: `deploy/docker-compose.yml` (api service: volumes + environment)
- Modify: `deploy/deploy.sh` (add mkdir -p before compose up)

- [ ] **Step 1: Add LOG_DIR env var and volume mount to docker-compose.yml**

In `deploy/docker-compose.yml`, in the `api` service:

Add `LOG_DIR: /app/logs` to the `environment` block (after `UPLOADS_DIR`):

```yaml
      UPLOADS_DIR: /app/uploads
      LOG_DIR: /app/logs
```

Add `./logs/api:/app/logs` to the `volumes` block (after `api_uploads`):

```yaml
    volumes:
      - api_uploads:/app/uploads
      - ./logs/api:/app/logs
```

The `read_only: true` hardening on the container is NOT affected — Docker applies read-only to the overlay filesystem; explicitly mounted volumes remain writable.

- [ ] **Step 2: Add mkdir -p to deploy.sh before compose up**

In `deploy/deploy.sh`, add these lines immediately before the `docker compose up -d --build` line (currently line 66):

```bash
echo "==> Ensuring log directories exist..."
mkdir -p "$SCRIPT_DIR/logs/api"
```

The full section around the change:

```bash
echo "==> Ensuring log directories exist..."
mkdir -p "$SCRIPT_DIR/logs/api"

echo "==> Rebuilding and starting stack..."
docker compose -f "$COMPOSE_FILE" up -d --build
```

- [ ] **Step 3: Verify docker-compose syntax**

```bash
docker compose -f deploy/docker-compose.yml config --quiet
```

Expected: no output (valid YAML).

- [ ] **Step 4: Commit**

```bash
git add deploy/docker-compose.yml deploy/deploy.sh
git commit -m "feat(deploy): bind-mount host log directory for persistent API logs"
```

---

## Task 6: Full CI Pass and PR

- [ ] **Step 1: Run all backend CI checks**

```bash
cd server
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/bandit -r app -c pyproject.toml -q
.venv/bin/pytest --tb=short -q
```

Expected: all pass.

- [ ] **Step 2: Run all frontend CI checks**

```bash
cd dashboard
npm run lint
npx tsc --noEmit
npm test -- --run
```

Expected: all pass.

- [ ] **Step 3: Push and open PR**

```bash
git push -u origin fix/admin-toggle-text-and-persistent-logs
gh pr create \
  --title "fix: admin toggle language + persistent API logs" \
  --body "$(cat <<'EOF'
## Summary
- Fixes misleading bot protection toggle description in admin settings — Turnstile always runs silently; toggle controls enforcement only
- Extracts `configure_logging()` to `app/core/logging_config.py` with dual-handler output: rotating plain-text file + JSON stdout
- Bind-mounts `deploy/logs/api/` on the VPS host so API logs survive `docker compose down` and deploys
- Deploy script creates the log directory idempotently before `docker compose up`

## Test plan
- [ ] Visual: load `/admin/settings`, confirm updated label and description
- [ ] `tail -f ~/WrzDJ/deploy/logs/api/app.log` on VPS after deploy — confirm HTTP access lines appear
- [ ] `docker compose logs api` still works (JSON stdout unaffected)
- [ ] `docker compose down && docker compose up -d --build` — confirm log file persists
- [ ] pytest: 4 new tests in `tests/test_logging_config.py` all pass
EOF
)"
```
