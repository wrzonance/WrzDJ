# WrzDJ Architecture

WrzDJ is a DJ song-request management system with five components:

- **Backend** — Python FastAPI (`server/`): SQLAlchemy 2.0, PostgreSQL, Alembic migrations.
- **Frontend** — Next.js 16+ / React 19 (`dashboard/`): TypeScript, vanilla CSS (dark theme).
- **Bridge** — Node.js DJ-equipment integration (`bridge/`): plugin system for Denon StageLinQ,
  Pioneer PRO DJ LINK, Serato DJ, Traktor Broadcast.
- **Bridge App** — Electron GUI for the bridge (`bridge-app/`): React + Vite, cross-platform installers.
- **Kiosk** — Raspberry Pi deployment (`kiosk/`): setup scripts, systemd services, Cage + Chromium.

Cross-references: `docs/PLUGIN-ARCHITECTURE.md` (bridge plugins), `docs/LLM-PLUGIN.md` (LLM gateway),
`docs/HUMAN-VERIFICATION.md`, `docs/RECOVERY-IP-IDENTITY.md`, `docs/RUNBOOK.md`, `SECURITY.md`.

## Roles & Permissions

- User roles: `admin`, `dj`, `pending` — `String(20)` column on the User model.
  - `admin`: full access incl. `/api/admin/*` and the admin dashboard.
  - `dj`: standard DJ access — create events, manage requests, search music.
  - `pending`: can login and view `/me` only; blocked from DJ features until approved.
- Auth dependencies in `server/app/api/deps.py`:
  - `get_current_user` — any authenticated user (used for `/me`).
  - `get_current_active_user` — rejects `pending` (all DJ endpoints).
  - `get_current_admin` — rejects non-admin (`/api/admin/*`).
- Bootstrap user (`BOOTSTRAP_ADMIN_USERNAME`) gets `role="admin"`. Self-registered users get
  `role="pending"` until approved.

## Self-Registration

- `POST /api/auth/register` — rate-limited (3/min), creates a `pending` user.
- `GET /api/auth/settings` — public; returns `registration_enabled` + `turnstile_site_key`.
- Toggle from admin Settings (DB-backed, not env var). Cloudflare Turnstile required
  (`server/app/services/turnstile.py`); skipped in dev when no `TURNSTILE_SECRET_KEY`.
- Frontend: `dashboard/app/register/page.tsx`. Login conditionally shows "Create Account".

## Admin Dashboard

Pages under `dashboard/app/admin/` with a sidebar layout; non-admins redirected to `/dashboard`.

- Overview (`/admin`): stats grid (users, events, requests, pending count).
- Users (`/admin/users`): CRUD, role filter tabs, approve/reject pending.
- Events (`/admin/events`): view/edit/delete any event regardless of owner.
- Settings (`/admin/settings`): toggle registration, human-verification enforcement, search rate limit.
- Integrations (`/admin/integrations`): service-health dashboard — toggle
  Spotify/Tidal/Beatport/Bridge, manual health checks, status indicators.
- AI (`/admin/ai`): LLM connector policy + per-DJ table + usage rollup.

## System Settings (DB-backed singleton)

- `system_settings` table (`server/app/models/system_settings.py`); service
  `server/app/services/system_settings.py` lazy-creates defaults if missing.
- Fields: `registration_enabled`, `human_verification_enforced`, `search_rate_limit_per_minute`,
  integration toggles `spotify_enabled` / `tidal_enabled` / `beatport_enabled` / `bridge_enabled`
  (all default `True`).

## Kiosk Pairing (server-side)

- Model `server/app/models/kiosk.py`: `pair_code` (6-char, safe alphabet excl. O/0/I/1),
  `session_token` (64-hex), `status` (`pairing`/`active`), `pair_expires_at` (5-min TTL).
- Service `server/app/services/kiosk.py`: create/complete pairing, assignment polling, expiry cleanup.
- Flow: kiosk `POST /api/public/kiosk/pair` → displays QR → DJ scans → authenticates → selects event
  at `/kiosk-link/{code}` → `POST /api/kiosk/pair/{code}/complete` → kiosk polls status → redirects to
  `/e/{event_code}/display`.
- Frontend: `dashboard/app/kiosk-pair/page.tsx` (device), `dashboard/app/kiosk-link/[code]/page.tsx`
  (DJ event picker, auth-gated). Session token persisted in localStorage; DJ management via
  `PairedKiosksCard` (list/rename/reassign/unpair).

## API Structure

- Admin: `server/app/api/admin.py` (`/api/admin/`, incl. integration health/toggle).
- Authenticated DJ: `events.py`, `requests.py`, `search.py`, `beatport.py`, `tidal.py`.
- `/api/events` combines `events.py` with `events_requests.py`, `events_recommendations.py`,
  `events_exports.py`, and `events_collection.py`. The collection module owns collection
  settings/sync, pending and bulk review, and bulk enrichment.
- Kiosk: `kiosk.py` — DJ endpoints `/api/kiosk/` + public pairing `/api/public/kiosk/`.
- Public (no auth): `public.py`, `votes.py`, `bridge.py`, auth settings/register.
- Rate limiting via slowapi: `@limiter.limit("N/minute")`.
- Global error handler prevents token/credential leakage (generic 500 in production).
- Frontend API client `dashboard/lib/api/index.ts` — singleton `ApiClient`; browser requests send the
  HttpOnly session cookie with `X-Requested-With: WrzDJ` for CSRF protection. Explicit bearer
  tokens remain supported for non-browser consumers. The 401 interceptor redirects to login;
  generated types mirror the exported Pydantic schemas.

## Dashboard UI Ownership

- Event components under `dashboard/app/(dj)/events/[code]/components/` are grouped by feature:
  `recommendations`, `providers`, `kiosk`, `requests`, `voting`, and `management`, with tests
  beside each group. Recommendation result/loading/acceptance state belongs to
  `recommendations/useRecommendationResults.ts`; playlist selection has its own hook.
  `useEventLiveStatus.ts` owns play history, now-playing, and bridge state, discarding responses
  from old routes and preserving newer bridge updates received through SSE.
- Account-only provider and preference components live in `dashboard/app/(dj)/account/components/`.
  Collection form fields shared by event creation and event settings live in
  `dashboard/components/events/collection/`.
- `dashboard/app/(dj)/dashboard/components/CreateEventWorkflow.tsx` owns the event-creation form
  and optional collection setup; the dashboard route owns event loading and the event list.
- The guest join route owns identity and request loading. `RequestFeed` owns tabs and request-row
  presentation, and `useGuestRequestVoting` owns optimistic voting and retryable failures.
  `NicknameGate` remains shared by the join and collect routes.
- API domain clients under `dashboard/lib/api/domains/` share transport and error parsing from
  `dashboard/lib/api/transport.ts`; callers use the stable `@/lib/api` entry point.

## Request Status Flow

```text
NEW → ACCEPTED → PLAYING → PLAYED
NEW → REJECTED
REJECTED → NEW (re-open)
```

- State machine enforced: invalid transitions (e.g. NEW → PLAYED) return 400.
- **Single-active playing**: only one request per event may be PLAYING; marking a new one PLAYING
  auto-transitions the previous to PLAYED (`clear_other_playing_requests()` in `request.py`).
- Manual "Mark Playing" also upserts `NowPlaying` (`set_manual_now_playing()` in `now_playing.py`)
  so kiosk displays show manually-played tracks. Bridge auto-detection overrides all playing requests.

## Key Backend Services (`server/app/services/`)

- `request.py` — CRUD, deduplication, bulk accept, single-active playing constraint.
- `vote.py` — idempotent voting with atomic increments.
- `event.py` — event lifecycle, status computation.
- `now_playing.py` — NowPlaying table, manual/bridge sync, auto-hide, play-history archival.
- `providers/beatport.py` — public Beatport facade. OAuth2 + PKCE S256 and account lifecycle,
  catalog queries, playlists, and manual request links live in `beatport_account.py`,
  `beatport_catalog.py`, `beatport_playlists.py`, and `beatport_manual_link.py` respectively.
  Shared protocol values and duration parsing live in `beatport_common.py`; catalog and playlist
  responses share the track-result mapper in `beatport_mapping.py`.
- `providers/tidal.py` — public Tidal facade. Account/device login, search, playlist lifecycle,
  and request synchronization live in `tidal_account.py`, `tidal_search.py`,
  `tidal_playlists.py`, and `tidal_request_sync.py` in the same package. These use the lower-level
  `tidal_session.py`, `tidal_catalog.py`, and `tidal_results.py` boundaries. Catalog operations bind
  their session and result conversion directly; `tidal_search.py` owns track-match selection.
- `admin.py` — user/event CRUD, system stats, last-admin protection (`count_admins(db) > 1`).
- `integration_health.py` — health checks & admin toggles for external services.
- `search_merge.py` — dedupes results across Spotify/Beatport.
- `providers/musicbrainz.py` (rate-limited 1 req/s), `providers/soundcharts.py` — metadata/discovery.
- `providers/spotify.py` / `providers/listenbrainz.py` — Spotify search and ListenBrainz discovery.
- `intent_parser.py`, `track_normalizer.py`, `version_filter.py` — version/remix handling.
- `music_matching.py` — shared Camelot key parsing/compatibility and BPM/genre scoring primitives
  used by recommendations, SetBuilder, and request ordering; feature ranking remains in each caller.
- `tracks/profile.py`, `tracks/profile_mappers.py`, and `tracks/enrichment.py` — shared track
  profiles, provider-result conversion, and Beatport/Tidal metadata backfill used by recommendations
  and SetBuilder. Enrichment returns metadata; callers own master-store writes.
- `banner.py` — banner image processing (resize 1920x480, WebP q92, desaturate, color extraction;
  path-traversal protected via `Path.is_relative_to()`; migration `009_add_event_banner.py`).

## LLM Gateway (provider-agnostic)

`server/app/services/llm/` — connector-based dispatch usable by any agentic feature. See
`docs/LLM-PLUGIN.md`. Privacy/credential rules live in `SECURITY.md`.

- `gateway.py` — `Gateway.dispatch(db, actor, request, *, purpose)` resolves a connector
  (per-DJ MRU → org default → `NoLlmConfigured`) and routes through the matching adapter.
  Gateway telemetry and connector status updates use a separate transaction on the caller's
  database engine; pending agent edits remain owned by the calling route and can roll back.
- `base.py` (`ChatRequest`/`ChatResponse`/`ToolSpec`/`LlmAdapter` ABC), `registry.py`
  (connector_type → adapter), `tool_translation.py` (JSON-Schema ↔ per-provider tool shape),
  `url_validator.py`, `exceptions.py`.
- `connector_payloads.py` builds typed connector inputs and credentials;
  `connector_storage.py` owns connector CRUD and transaction boundaries;
  `connector_preferences.py` persists feature pins; `connector_telemetry.py` owns usage/audit data.
- Adapters: `openai_apikey.py`, `openai_compatible.py` (Hermes Agent, Ollama, vLLM, LMStudio),
  `anthropic_apikey.py` (uses the `anthropic` SDK).
- Models: `LlmConnector` (encrypted creds), `LlmCallLog`, `LlmAuditEvent`.
- Endpoints: admin `/api/admin/llm/*` (policy, force-revoke, usage); DJ `/api/llm/connectors`
  (list/create/rotate/test/delete, rate-limited, scoped to user). UIs: `/admin/ai`, `/settings/ai`.
- **Credentials**: there is **no env-var credential path**. The one-shot Alembic migration
  `047_admin_ai_oauth` reads `ANTHROPIC_API_KEY` once on first upgrade to seed a connector; the
  legacy env-var fallback was removed in #343 — the connector system is the sole credential source.
  `ANTHROPIC_MODEL` (default `claude-haiku-4-5-20251001`) is retained only as a default model-name
  label and for admin model-listing.

## Recommendation Engine

`server/app/services/recommendation/` — multi-stage pipeline. Routes through the LLM gateway
(`actor = event.created_by`, `purpose = "recommendation"`); `call_llm` requires a `db` session.

- `service.py` (orchestrator: profile → search → score → dedupe), `candidate_search.py`
  (provider searches and candidate discovery), `enrichment.py` (event-track selection and
  enrichment through the shared `tracks/enrichment.py` Beatport/Tidal operation),
  `scorer.py` (BPM compat, harmonic mixing, genre affinity, artist-diversity penalty),
  `camelot.py` (Camelot wheel, half/double-time),
  `llm_client.py` (gateway-backed, forced `tool_use` schema), `llm_hooks.py`, `template.py`
  (playlist "vibe" source), `mb_verify.py` (MusicBrainz verification to detect AI-generated filler),
  `soundcharts_candidates.py` (two live Soundcharts-backed candidate generators: discovery search
  and seed-based related-tracks). Full provider/pipeline detail: `docs/ENRICHMENT.md` §3.2.
- Three modes: From Requests (event profile), From Playlist (template), AI Assist (Claude Haiku).
- Endpoints in `events_recommendations.py`, included by `events.py`:
  `POST /{code}/recommendations`, `.../from-template`, `.../llm`,
  `GET /{code}/playlists`.

## Multi-Service Playlist Sync & Enrichment

- `server/app/services/sync/` — plugin-based adapters: `base.py` (`PlaylistSyncAdapter` ABC),
  `tidal_adapter.py`, `beatport_adapter.py`, `orchestrator.py` (coordinate + dedupe + enrich; only
  a thin re-export layer for enrichment — see next bullet), `registry.py`. Per-service results
  stored in `sync_results_json`.
- `enrich_request_metadata` — defined in `enrichment_pipeline.py`; `orchestrator.py` only imports
  and re-exports it. Priority cascade: (0) direct fetch by track ID from Beatport/Tidal URLs; (0b)
  ISRC match for Spotify; (1) MusicBrainz artist genre; (2) Beatport fuzzy; (3) Tidal fuzzy; (4)
  per-event BPM half/double-time correction (mutates the request only — the cascade's store write
  keeps the canonical pre-correction BPM); (5) Soundcharts audio features (gated, ISRC-only).
  `_apply_enrichment_result()` only fills missing fields.
  `_find_best_match()` scores title 60% + artist 40% with original-version bonus / remix penalty /
  BPM tiebreaker. Resolved fields upsert into the master `tracks` store via a precedence-gated
  cache-aside path that skips the *core* cascade (steps 0-3) for already-trusted rows — energy
  backfill can still call out. Full provider/precedence detail: `docs/ENRICHMENT.md`.

## WrzDJSet (Set Builder)

The set builder lets a DJ pre-plan a performance as an ordered timeline of slots backed by a
candidate-track *pool*, with a derived energy curve, multi-source vibe tagging, sharing, and export
to real DJ tooling. Backend: `server/app/api/setbuilder.py` aggregates the pool, export, pairing,
and collaboration routers at `/api/setbuilder`; `setbuilder_templates.py` and
`setbuilder_share.py` are mounted separately, with public reads at `/api/public/setbuilder`.
These routes use `server/app/services/setbuilder/`.
Frontend: `dashboard/app/(dj)/setbuilder/`.

**Data model** (`server/app/models/`):

- `set.py` — `Set` (owner-scoped; `status`, `sharing_mode`, CSPRNG `share_token`, BPM floor/ceiling,
  `key_strictness`, optional `event_id` / `tidal_playlist_id`), `SetSlot` (ordered `position`,
  namespaced `track_id`, `locked`, `target_energy`, transition score/warnings), `SetCurvePoint`
  (energy 0–10 at `position_sec`, slow-window markers), `SetCollaborator` (editor/viewer).
- `set_pool.py` — `SetPoolSource` (per-import provenance) + `SetPoolTrack` (candidate tracks,
  deduped on ISRC then normalized artist+title).
- `track_vibe.py` — `TrackVibe` (GLOBAL LLM-enrichment cache keyed by track + prompt/schema version)
  + `TrackVibeOverride` (per-DJ vote feeding community consensus).
- Migrations: `046_add_setbuilder_tables`, then (apply order, which is **not** numeric —
  verify with `alembic history`) `054_add_set_share_token` → `053_add_setbuilder_pool_tables` →
  `055_add_curve_templates`, and later `057_add_vibe_consensus_settings`.

**Services** (`server/app/services/setbuilder/`):

- `set_service.py` — owner-scoped CRUD; a missing-or-unowned set returns **404 (not 403)** to avoid
  leaking existence (matches `deps.get_owned_event_by_id`).
- `pool.py` — the candidate-track surface; tracks flow in from event requests, Tidal, Beatport,
  public playlist URL, and manual search, each tagged with its `SetPoolSource` for per-source removal.
  `pool_sources.py` owns provider fetches and ingestion; `pool_types.py` defines their data shapes.
- `playlist_url.py` — **parses but never fetches** user-supplied playlist URLs (SSRF defense):
  https-only, exact-host allowlist, strict ID charset; importers then call official APIs by ID.
- `curve.py` — energy-curve templates (built-in + per-DJ) interpolated piecewise-linear onto each
  slot's `target_energy` at its timeline midpoint; the curve is *derived*, not stored per-slot twice.
- `vibe_enrichment.py` / `vibe_resolver.py` / `community_vibe.py` — three-tier vibe precedence
  (own → community → LLM cache), resolved per-field at read time (nothing materialized). The LLM tier
  routes through the gateway (`purpose="set_builder"`), batched forced-`tool_use`, cached globally so
  a second DJ pays nothing; the community tier is gated by `vibe_consensus_min_sample` /
  `vibe_consensus_max_stddev` (System Settings) so noise never masquerades as consensus.
- `taste_profile.py` — per-DJ calibration layered on top of the resolved vibe, never a fourth
  resolution tier: shifts a non-"own" resolved energy by a capped delta learned from that DJ's own
  historical vibe edits.
- `coverage.py` — read-only pre-build pool-readiness check: reports what fraction of a set's pool
  carries all five pool→builder contract fields (bpm/key/genre/duration/energy), feeding a soft,
  overridable build warning. Full vibe/energy source-of-truth detail: `docs/ENRICHMENT.md` §3.3/§4.
- `exports/export_common.py` / `exports/export_files.py` / `exports/export_tidal.py` — export the
  ordered timeline (falling back to pool order until timeline auto-fill lands): Tidal playlist
  (OAuth + fuzzy match), Rekordbox
  XML (`DJ_PLAYLISTS 1.0.0`, synthetic `file://` Location the DJ relinks), M3U8, and plaintext. A
  two-phase preflight reports **unresolved** tracks (409) so the DJ can skip them.
- `share_service.py` — share-token + duplicate logic; the token is the *sole* capability for the
  public read-only view and never grants a mutating route.

**Endpoints** (all `/api/setbuilder` unless noted; rate-limited per route):

- Sets/slots: CRUD `sets`, `sets/{id}/slots`, slot target-energy, vibe-windows, curve templates + apply.
- Pool: `sets/{id}/pool` plus `pool/import/{event,tidal,beatport,url,manual}`, `pool/url-preview`,
  per-source/-track removal, `pool/vibes` (read, `60/min`) + `pool/vibes` enrich (`5/min`).
- Export: `export/preflight`, `export/tidal`, `export/file` (Rekordbox XML / M3U8 / plaintext download).
- Sharing: `sets/{id}/share` (create/rotate/revoke), `sets/{id}/duplicate`, and public token-gated
  `GET /api/public/setbuilder/...` (`30/min`).

## Bridge Plugin System

See `docs/PLUGIN-ARCHITECTURE.md` for full details.

- Built-in plugins: StageLinQ (Denon), Pioneer PRO DJ LINK, Serato DJ, Traktor Broadcast.
- `plugins/` owns plugin contracts, registration, adapters, and event translation; `deck/` owns
  deck state; `transport/` owns backend delivery, retries, and command polling; `runtime/` owns
  configuration and lifecycle; `shared/` holds common event, track, logging, and time primitives.
  `index.ts` is the CLI entry and `electron-api.ts` is the stable Electron package entry.
- Plugins self-describe via `info` / `capabilities` / `configOptions` (`PluginConfigOption` declares
  type, default, min/max, label). Registry exposes `getPluginMeta()` / `listPluginMeta()` (IPC-safe);
  bridge-app SettingsPanel is fully data-driven — no hardcoded plugin UI.
- Pioneer uses `alphatheta-connect` (maintained `prolink-connect` fork w/ encrypted Rekordbox DB).
  Serato watches binary session files (pure TS parsing, `serato-session-parser.ts`). Traktor uses
  Node `http` only. StageLinQ uses the `stagelinq` npm package.

## Bridge App (Electron)

- Main process: auth, events API, bridge runner, persistent `electron-store`. Renderer: React UI
  (login, event selection, bridge controls, status). IPC via `contextBridge` — renderer has no Node
  access. Imports the supported `@wrzdj/bridge/electron` package entrypoint. Main startup
  explicitly registers built-in plugins before creating windows or IPC handlers.
- Installers: `.exe` (Windows), `.dmg` (macOS), `.AppImage` (Linux) via electron-forge.
- **Externalization**: plugins with npm deps (stagelinq, alphatheta-connect) must be externalized
  from Vite through `externalDeps` in `bridge-app/vite.main.config.ts`. Their dependencies belong
  to `bridge/package.json`; `packaging/stage-bridge-dependencies.ts` stages their full runtime
  dependency graph for Electron packaging. Install bridge dependencies before bridge-app dependencies.
  `AutoUnpackNativesPlugin` unpacks `.node` files, which are rebuilt for Electron's ABI.

## Kiosk (Raspberry Pi)

The `kiosk/` directory turns a fresh Pi OS Lite into a locked-down event display: boots into Cage
(Wayland) + Chromium loading `/kiosk-pair` — no desktop, no escape routes.

- Key files: `kiosk/setup.sh` (idempotent main setup), `kiosk/wrzdj-kiosk.conf` (template), the WiFi
  captive portal (`kiosk/wifi-portal/portal.py`, Python stdlib only, port 80;
  `dnsmasq-captive.conf`), systemd units (`wrzdj-kiosk.service` reference-only,
  `wrzdj-wifi-portal.service`, watchdog `service`/`timer`/`sh`), optional
  `kiosk/overlayfs/setup-overlayfs.sh`.
- Portal responsibilities: `portal.py` owns HTTP and coordinated radio operations;
  `portal_network.py` contains NetworkManager commands and connectivity probes;
  `portal_config.py` loads typed service settings; `portal_pages.py` renders escaped HTML and
  holds the browser assets; `portal_requests.py` validates WiFi input before radio changes.
  `portal_state.py` gives each server its own configuration, network cache and radio locks.
  `portal_defaults.py` and `portal_types.py` share defaults and payload
  definitions. Runtime uses Python stdlib; the test suite also runs the browser script with Node.js.
- **WiFi captive portal**: portal starts on boot; Chromium always opens `http://localhost` first.
  If WiFi unconfigured → pre-scan, start hotspot (`WrzDJ-Kiosk`), serve setup page (touchscreen +
  phone captive portal, DNS redirect to `10.42.0.1`). If configured → JS redirect to `KIOSK_URL`.
- **Design decisions**: Cage launches from `/home/kiosk/.bash_profile` on tty1 (needs logind seat;
  self-healing). Dedicated least-privilege `kiosk` user (groups `input`/`video`/`render`). OverlayFS
  opt-in (SD protection at the cost of localStorage; re-pairs in ~30s). Config at
  `/etc/wrzdj-kiosk.conf` (change URL + restart, no re-run). No backend/frontend changes — pure
  deployment infra. User guide: `kiosk/README.md`.

## CI/CD Layout

- `.github/workflows/ci.yml` — backend, frontend, bridge, bridge-app, kiosk, and docker-build jobs. Backend:
  ruff lint + format, bandit, pip-audit, pytest w/ coverage gate, Alembic `upgrade head && check`.
  Frontend/bridge/bridge-app: ESLint (frontend), `tsc --noEmit`, vitest w/ coverage, npm audit.
  Kiosk runs portal HTTP/process/browser-script tests. Docker smoke tests build backend and
  frontend images and check deployment provisioning and PostgreSQL upgrades.
- `.github/workflows/codeql.yml` — CodeQL SAST (Python & JS/TS).
- **Release** (`release.yml`): triggers on tag push (`v*`), not PR merge. Date-based versioning
  `v2026.02.07` (same-day suffix `.2`). Builds bridge-app installers across 3 platforms (matrix,
  Linux = AppImage); bundles deploy scripts as `.tar.gz`.
- Pre-commit hook (`./scripts/setup-hooks.sh`): staged Python files in `server/` only — ruff lint,
  ruff format, bandit.

## Common Pitfalls

- **Alembic model/migration drift**: CI runs `alembic check`. `op.create_index` needs `index=True`
  on the model column; added columns must match the migration exactly (type, nullable, defaults). Run
  `cd server && .venv/bin/alembic upgrade head && .venv/bin/alembic check` before pushing.
- `next-env.d.ts` is auto-modified by builds — `git checkout` it before committing. Frontend
  `next build` is stricter than dev for TS validation.
- `request.client.host` in `events.py` submit_request differs from the `X-Forwarded-For` logic in
  `votes.py` — known inconsistency behind proxies.
- Adding fields to shared interfaces (e.g. `PublicRequestInfo`) requires updating test fixtures that
  construct those types.
- Admin endpoints need `get_current_admin`; DJ endpoints need `get_current_active_user` (not
  `get_current_user`, which allows pending). Last-admin protection: verify `count_admins(db) > 1`
  before demoting/deleting/deactivating any admin.
- Banner upload uses `File(...)` not `UploadFile(...)`; banner colors stored as JSON string
  (`json.loads`/`json.dumps`). `api_uploads` Docker volume persists uploads across restarts.
- Beatport OAuth uses PKCE (S256); `beatport_oauth_code_verifier` stored temporarily on the user model.
- Services calling only sync APIs (Spotify, Beatport search) should not be `async`.
- Three Turnstile widgets coexist: `/register`, session bootstrap on `/join` + `/collect`
  (`useHumanVerification`), and per-action OTP (`EmailVerification.tsx`, `NicknameGate.tsx`). They share
  `lib/turnstile.ts` but are independent instances.

## Upstream Bridge-Plugin Dependency Health

Bridge plugins depend on community projects for protocol support — periodically check upstream health
(unmaintained / broken / API-changed libraries may need updates or replacements).

| Package | Plugin | GitHub | Check |
|---|---|---|---|
| `stagelinq` | StageLinQ (Denon) | chrisle/StageLinq | releases, issues, Denon firmware protocol changes |
| `alphatheta-connect` | Pioneer PRO DJ LINK | chrisle/alphatheta-connect | releases, PRO DJ LINK changes, Rekordbox DB encryption, `better-sqlite3-multiple-ciphers` compat |

Reference implementations (no runtime dep, used for format research): `serato-tags`
(Holzhaus/serato-tags), `SSL-API` (bkstein/SSL-API), `whats-now-playing`, `traktor_nowplaying`.
Traktor and Serato plugins use only Node built-ins. Check before major bridge version bumps, when a DJ
reports detection issues after a software update, when audit flags those packages, or quarterly.
