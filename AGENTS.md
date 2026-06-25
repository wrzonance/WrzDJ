# WrzDJ — Claude Code Instructions

Follows the global `~/.claude/rules` (code · workflow · security · agents). This file holds
only WrzDJ-specific facts and overrides. Architecture: `ARCHITECTURE.md`. Security posture:
`SECURITY.md`.

WrzDJ is a full-stack DJ song-request system: FastAPI backend (`server/`) + Next.js/React 19
frontend (`dashboard/`) + Node bridge for DJ equipment (`bridge/`) + Electron bridge app
(`bridge-app/`) + Raspberry Pi kiosk (`kiosk/`). See `ARCHITECTURE.md` for the full map.

## Overrides vs. the global rules

- **Coverage is an ENFORCED hard gate, not a diagnostic.** Backend pytest fails under the
  configured threshold via `--cov-fail-under` in `server/pyproject.toml` (CI runs
  `pytest --cov=app`). New backend code must keep coverage at or above the gate — do not lower
  the threshold to pass.
- **Git workflow** (project specifics layered on the global branch-safety rule):
  - Create the feature branch BEFORE making any change. Never edit code while on `main`.
  - Branch prefixes: `feat/`, `fix/`, `refactor/`, `docs/`, `chore/`. PR into `main`; never push
    directly to `main`. Run CI checks locally before pushing.
  - GitHub PRs created by Claude or Codex must be drafts (`gh pr create --draft` or connector
    `draft: true`); do not create ready-for-review PRs directly.
- **Code style**:
  - Backend: ruff (line-length 100; rules E, F, I, UP). SQLAlchemy `== None` / `== True` allowed
    (E711/E712 ignored); forward refs allowed in models (F821 ignored).
  - Frontend: **vanilla CSS + inline React styles — NO Tailwind, no UI framework.** Dark theme
    (bg `#0a0a0a`, cards `#1a1a1a`, text `#ededed`), mobile-first. Styles in
    `dashboard/app/globals.css` or inline.
- **Versioning**: date-based git tags (e.g. `v2026.02.07`; same-day suffix `v2026.02.07.2`).
  Releases trigger on tag push, not PR merge (`release.yml`).

## Security posture → see `SECURITY.md`

Key project rules (full detail in `SECURITY.md`): secrets via the `EncryptedText` TypeDecorator
(never plaintext); public endpoints require rate limiting + Pydantic input validation + output
sanitization; never expose internal errors/stack traces; parameterized queries only (no f-string
SQL); no `eval`/`exec` on user data; guest public endpoints require an HMAC-signed `wrzdj_human`
cookie issued after Turnstile verification; guest identity is `guest_id` only (no IP-derived
columns); dependency CVE vigilance (pip-audit / npm audit — don't silence without justification);
prompt-injection hygiene.

## Local Development

### Prerequisites
- PostgreSQL 16 via Docker: `docker compose up -d db`
- Python 3.11+ with venv at `server/.venv/`
- Node.js 22+

### Run services
```bash
docker compose up -d db                                          # database

# Backend (from server/)
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Frontend (from dashboard/) — discover the machine's LAN IP first
NEXT_PUBLIC_API_URL="http://LAN_IP:8000" npm run dev
```

### LAN testing (phone)
- Bind to `0.0.0.0`; use the discovered LAN IP. Set `CORS_ORIGINS=*` for dev,
  `PUBLIC_URL=http://LAN_IP:3000` for QR codes. Frontend dev server already binds `0.0.0.0`.

### Environment
- `.env` at repo root holds all local dev config; see `.env.example` for the full key list.
- Core: `DATABASE_URL`, `JWT_SECRET`, `SPOTIFY_CLIENT_ID/SECRET`, `CORS_ORIGINS`, `PUBLIC_URL`,
  `NEXT_PUBLIC_API_URL`.
- Turnstile (CAPTCHA): `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`.
- Uploads: `UPLOADS_DIR` (defaults `server/uploads/` locally, `/app/uploads` in Docker).
- Encryption: `TOKEN_ENCRYPTION_KEY` (Fernet, 44-char base64) — required in production (missing =
  fatal startup error). `HUMAN_COOKIE_SECRET` (32 bytes base64) — required in production.
- Beatport: `BEATPORT_CLIENT_ID/SECRET`, `BEATPORT_REDIRECT_URI`, `BEATPORT_AUTH_BASE_URL`.
- Soundcharts: `SOUNDCHARTS_APP_ID`, `SOUNDCHARTS_API_KEY`.
- LLM (Anthropic): **no env-var credential path** — credentials live in the LLM Gateway connector
  system (see `ARCHITECTURE.md`). `ANTHROPIC_MODEL` (default `claude-haiku-4-5-20251001`) is only a
  default model-name label; the env-var fallback was removed in #343.

## CI Checks (run before pushing — mirror `.github/workflows/ci.yml`)

### Backend (from `server/`)
```bash
.venv/bin/ruff check .                        # lint (E, F, I, UP)
.venv/bin/ruff format --check .               # format check (line-length 100)
.venv/bin/bandit -r app -c pyproject.toml -q  # security scan
.venv/bin/pytest --tb=short -q                # tests + enforced coverage gate
.venv/bin/alembic upgrade head && .venv/bin/alembic check   # migration drift check
```
Auto-fix: `.venv/bin/ruff format .` and `.venv/bin/ruff check --fix .`.

### Frontend (from `dashboard/`)
```bash
npm run lint              # ESLint
npx tsc --noEmit          # TypeScript (strict)
npm test -- --run         # Vitest
```

### Bridge / Bridge App (from `bridge/` and `bridge-app/`)
```bash
npx tsc --noEmit
npm test -- --run
```

## Testing Notes

- **Backend (pytest)**: config in `server/pyproject.toml` `[tool.pytest.ini_options]`. Test DB is
  SQLite in-memory (not PostgreSQL). Fixtures in `server/tests/conftest.py`: `db`, `client`,
  `test_user`, `auth_headers`, `admin_user`, `admin_headers`, `pending_user`, `pending_headers`,
  `test_event`, `test_request`. TestClient host is `"testclient"` (visible to slowapi as the
  rate-limit key; not stored elsewhere). Single file: `.venv/bin/pytest tests/test_requests.py -v`.
- **Frontend (vitest)**: config `dashboard/vitest.config.ts`, env jsdom. Tests at
  `**/__tests__/**/*.test.{ts,tsx}` and `**/*.test.{ts,tsx}`. When adding fields to shared types
  (e.g. `PublicRequestInfo`), update test fixtures too.
- Pin every bug-fix with a regression test referencing the commit SHA.

## Frequent Pitfalls (full list in `ARCHITECTURE.md`)

- **Alembic drift**: CI runs `alembic check`. `op.create_index` needs `index=True` on the model
  column; added columns must match the migration exactly. Run upgrade + check locally first.
- `next-env.d.ts` is auto-modified by builds — `git checkout` it before committing.
- Admin endpoints need `get_current_admin`; DJ endpoints need `get_current_active_user` (not
  `get_current_user`, which allows pending). Last-admin protection: `count_admins(db) > 1` before
  demoting/deleting/deactivating an admin.
- `TOKEN_ENCRYPTION_KEY` / `HUMAN_COOKIE_SECRET` must be set in production.
- Request status transitions are state-machine-enforced (invalid → 400).

## Documentation Map

- `ARCHITECTURE.md` — full multi-service architecture, services, CI/CD, kiosk, pitfalls.
- `SECURITY.md` — security posture and project-specific rules.
- `docs/PLUGIN-ARCHITECTURE.md`, `docs/LLM-PLUGIN.md`, `docs/HUMAN-VERIFICATION.md`,
  `docs/RECOVERY-IP-IDENTITY.md`, `docs/RUNBOOK.md`, `docs/CONTRIB.md`.
- `AGENTS.md` — GitNexus code-intelligence index (auto-generated; do not hand-edit).
