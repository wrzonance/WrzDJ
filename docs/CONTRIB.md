# Contributing to WrzDJ

## Development Workflow

1. Create a feature branch from `main`
2. Make changes, run CI checks locally
3. Push and open a PR into `main`
4. Never commit directly to `main`

### Branch Naming

| Prefix | Use |
|--------|-----|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `refactor/` | Code restructuring |
| `docs/` | Documentation only |
| `chore/` | Tooling, deps, CI |

### Commit Messages

```
<type>: <description>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`

## Environment Setup

### Prerequisites

- Docker + Docker Compose (for PostgreSQL 16)
- Python 3.11+ with venv
- Node.js 22+ with npm

### 1. Start the database

```bash
docker compose up -d db
```

### 2. Backend (server/)

```bash
cd server
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Frontend (dashboard/)

```bash
cd dashboard
npm install
NEXT_PUBLIC_API_URL="http://<LAN_IP>:8000" npm run dev
```

Determine your LAN IP with `ip addr` or `hostname -I` and substitute above.

### 4. Git hooks

```bash
./scripts/setup-hooks.sh
```

Installs a pre-commit hook that runs ruff lint, ruff format, and bandit on staged Python files.

### Environment Variables

All config lives in `.env` at the repo root. Key variables:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string |
| `JWT_SECRET` | Auth token signing key |
| `SPOTIFY_CLIENT_ID` | Spotify API credentials |
| `SPOTIFY_CLIENT_SECRET` | Spotify API credentials |
| `TIDAL_CLIENT_ID` | Tidal API credentials |
| `TIDAL_CLIENT_SECRET` | Tidal API credentials |
| `TIDAL_REDIRECT_URI` | Tidal OAuth callback URL |
| `CORS_ORIGINS` | Allowed origins (`*` for dev) |
| `PUBLIC_URL` | Base URL for QR codes (frontend) |
| `NEXT_PUBLIC_API_URL` | Backend URL for frontend fetch calls |
| `BRIDGE_API_KEY` | Bridge service authentication (all DJ-equipment plugins) |
| `BOOTSTRAP_ADMIN_USERNAME` | Auto-create admin on first startup |
| `BOOTSTRAP_ADMIN_PASSWORD` | Auto-create admin on first startup |
| `TOKEN_ENCRYPTION_KEY` | Fernet key encrypting OAuth tokens at rest (prod-fatal if unset) |
| `HUMAN_COOKIE_SECRET` | Signs the `wrzdj_human` verification cookie (prod-fatal if unset) |
| `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` | Cloudflare Turnstile (human verification + DJ self-reg) |
| `BEATPORT_CLIENT_ID` / `BEATPORT_CLIENT_SECRET` | Beatport OAuth credentials (search + playlist sync) |
| `ANTHROPIC_API_KEY` | Optional — enables AI Assist song recommendations |
| `RESEND_API_KEY` / `EMAIL_FROM_ADDRESS` | Email verification provider (one-time codes) |
| `SOUNDCHARTS_APP_ID` / `SOUNDCHARTS_API_KEY` | Soundcharts discovery API (BPM/key/genre) |

## Available Scripts

### Backend (server/)

| Command | Description |
|---------|-------------|
| `uvicorn app.main:app --reload` | Start dev server |
| `.venv/bin/ruff check .` | Lint (E, F, I, UP rules) |
| `.venv/bin/ruff format .` | Auto-format |
| `.venv/bin/ruff format --check .` | Format check (CI) |
| `.venv/bin/bandit -r app -c pyproject.toml -q` | Security scan |
| `.venv/bin/pytest --tb=short -q` | Run tests (85% coverage min) |
| `.venv/bin/pytest tests/test_requests.py -v` | Run single test file |
| `alembic upgrade head` | Apply migrations |
| `alembic revision --autogenerate -m "desc"` | Generate migration |

### Frontend (dashboard/)

| Command | Description |
|---------|-------------|
| `npm run dev` | Start dev server (binds 0.0.0.0) |
| `npm run build` | Production build |
| `npm run lint` | ESLint |
| `npx tsc --noEmit` | TypeScript type check (strict) |
| `npm test -- --run` | Run vitest suite |
| `npm run test:coverage` | Run with coverage report |

### Bridge (bridge/)

| Command | Description |
|---------|-------------|
| `npm start` | Start bridge (requires `.env`) |
| `npm run dev` | Start with file watching |
| `npm run build` | Compile TypeScript |
| `npm test` | Run vitest (watch mode) |
| `npm run test:run` | Run vitest once |

## CI Checks

**Run all of these locally before pushing.** They mirror `.github/workflows/ci.yml`.

### Backend

```bash
cd server
.venv/bin/ruff check .                        # Lint
.venv/bin/ruff format --check .               # Format
.venv/bin/bandit -r app -c pyproject.toml -q  # Security
.venv/bin/pytest --tb=short -q                # Tests + coverage
```

### Frontend

```bash
cd dashboard
npm run lint              # ESLint
npx tsc --noEmit          # Type check
npm test -- --run         # Vitest
```

### CI also runs (not typically needed locally)

- `pip-audit` — Python dependency vulnerability scan
- `npm audit --audit-level=high` — npm dependency vulnerability scan

## Testing

### Backend (pytest)

- Config: `server/pyproject.toml` `[tool.pytest.ini_options]`
- Test DB: SQLite in-memory (not PostgreSQL)
- Fixtures: `server/tests/conftest.py` — `db`, `client`, `test_user`, `auth_headers`, `admin_user`, `admin_headers`, `pending_user`, `pending_headers`, `test_event`, `test_request`
- TestClient default host: `"testclient"` — use for `client_fingerprint` in fixtures
- Coverage minimum: 85%

### Frontend (vitest)

- Config: `dashboard/vitest.config.ts`
- Environment: jsdom
- API client tests: `dashboard/lib/__tests__/api.test.ts`
- Display page tests: `dashboard/app/e/[code]/display/page.test.tsx`
- When adding fields to shared types (e.g. `PublicRequestInfo`), update test fixtures too

## Code Style

### Python

- Formatter/linter: ruff (line-length 100)
- Rules: E (errors), F (pyflakes), I (isort), UP (upgrades)
- SQLAlchemy `== None` / `== True` comparisons allowed (E711, E712 ignored)
- Forward references allowed in models (F821 ignored)

### TypeScript/React

- No UI component library — vanilla CSS + inline styles
- Dark theme: bg `#0a0a0a`, cards `#1a1a1a`, text `#ededed`
- Mobile-first layouts with flexbox
- All shared styles in `dashboard/app/globals.css`

## Common Pitfalls

- `next-env.d.ts` gets auto-modified by builds — `git checkout` it before committing
- When adding fields to shared interfaces, grep for test fixtures that construct those types
- TestClient fingerprint is `"testclient"`, not an IP address
- Backend tests use SQLite, not PostgreSQL — some SQL features may behave differently
- Events carry two public codes: the collection `code` routes `/collect` (gated pre-event flow), while `join_code` routes `/join`, `/e/{code}/display`, kiosk, OBS overlay, and bridge now-playing — resolve guest requests via the dual-code public resolver and never return the internal `event.id` on public endpoints
