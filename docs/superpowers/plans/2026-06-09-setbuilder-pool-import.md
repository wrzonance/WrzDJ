# WrzDJSet Pool Import (issue #388) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pool candidate-track surface for the set builder: import tracks from 4 source types (event requests, Tidal playlist, Beatport playlist, public playlist URL) plus manual single-track search, with per-source tagging, ISRC/fuzzy dedupe, and per-track / multi-select / per-source removal flows.

**Architecture:** Two new tables (`set_pool_sources`, `set_pool_tracks`) cascade under `sets`. All pool logic lives in NEW file `server/app/services/setbuilder/pool.py`; routes/schemas are strictly ADDITIVE in the shared `api/setbuilder.py` / `schemas/setbuilder.py`. Public-URL import never fetches the user URL — it parses a playlist ID with strict per-host regexes and calls official APIs (spotipy client-credentials for Spotify, the DJ's connected Tidal session for Tidal), which is the SSRF defense. Frontend: new `PoolPanel` + `ImportModal` components under `dashboard/app/(dj)/setbuilder/components/`, mounted in the existing builder page (additive), styled via additions to `setbuilder.module.css` using `var(--*)` tokens.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic (slot 053, down_revision "052"), pytest (SQLite in-memory), Next.js 16 / React 19 + vitest, vanilla CSS modules.

**Key design decisions (document in PR):**
- Public URL import supports **Spotify** (client-credentials, no user auth needed) and **Tidal** (requires DJ's connected Tidal session) end-to-end. Apple Music / YouTube / SoundCloud URL shapes are *recognized* by the validator but return `supported: false` with a clear message (no public-API credentials exist in this codebase for them). Beatport playlist URLs route DJs to the OAuth picker.
- Re-importing the same external source (same playlist / event) reuses the existing source row and imports only new tracks — dedupe stats report it; no duplicate source rows ever.
- Dedupe: exact ISRC match against pool first, then `sha256(normalize_artist + ":" + normalize_track_title)[:32]` signature (reuses `services/track_normalizer.py`). First import wins; original source tag preserved (per design footnote).
- `energy` is nullable — TrackVibe enrichment is issue #391; the badge renders empty bars until then.
- `track_id` is the namespaced free-form string convention from TrackVibe (`tidal:123`, `beatport:456`, `spotify:abc`, `request:789`), NOT an FK.
- Per-source removal is allowed for every kind incl. manual (prototype hides × for manual/recs buckets; our manual bucket is per-set and removable via track flows; the × is hidden for `manual` to match the prototype).

---

### Task 1: Models + migration 053

**Files:**
- Create: `server/app/models/set_pool.py`
- Modify: `server/app/models/__init__.py` (export), `server/app/models/set.py` (add `pool_sources`/`pool_tracks` relationships — additive)
- Create: `server/alembic/versions/053_add_setbuilder_pool_tables.py`

- [x] **Step 1: Write models**

`set_pool_sources`: id PK; set_id FK sets.id CASCADE idx; kind String(20) ("event"|"tidal"|"beatport"|"public_url"|"manual"); external_ref String(500) nullable; label String(200); meta String(200) nullable; created_at.
`set_pool_tracks`: id PK; set_id FK CASCADE idx; source_id FK set_pool_sources.id CASCADE idx; track_id String(255) nullable; title/artist String(255); album String(255) nullable; genre String(100) nullable; bpm Float nullable; key String(20) nullable; camelot String(3) nullable; energy Integer nullable; isrc String(15) nullable; duration_sec Integer nullable; artwork_url String(500) nullable; dedupe_sig String(64) idx; created_at; UniqueConstraint(set_id, dedupe_sig).

- [x] **Step 2: Migration 053** — revision "053", down_revision "052"; mirror model exactly (indexes ↔ index=True).
- [x] **Step 3: Verify** — `cd server && .venv/bin/alembic upgrade head && .venv/bin/alembic check` → "No new upgrade operations detected".
- [x] **Step 4: Commit** `feat(setbuilder): pool source/track models + migration 053`

### Task 2: Pool service core (dedupe, import, removal) — TDD

**Files:**
- Create: `server/app/services/setbuilder/pool.py`
- Test: `server/tests/test_setbuilder_pool_service.py`

- [x] **Step 1: Failing tests** — dedupe_signature equality for "Song (Original Mix)" vs "Song", feat. canonicalization; `import_candidates` returns (added, deduped) with ISRC-match dedupe across different titles; re-import same candidates → 0 added; `get_or_create_source` reuses row on same (set, kind, external_ref); `remove_tracks` scoped to set; `remove_source` deletes exactly its tracks and the source row.
- [x] **Step 2: Implement** — `PoolCandidate` dataclass (track_id, title, artist, album, genre, bpm, key, energy, isrc, duration_sec, artwork_url); `dedupe_signature(artist, title)` via `normalize_track()` + sha256[:32]; `camelot_code(key)` via `recommendation.camelot.parse_key`; `get_pool`, `get_or_create_source`, `import_candidates` (builds existing sig-set + isrc-set, skips blanks, single commit), `remove_tracks`, `remove_source`.
- [x] **Step 3: Run** `.venv/bin/pytest tests/test_setbuilder_pool_service.py -v` → PASS.
- [x] **Step 4: Commit** `feat(setbuilder): pool service — source tagging, ISRC+fuzzy dedupe, removal`

### Task 3: Candidate builders (event / tidal / beatport / manual / public URL)

**Files:**
- Modify: `server/app/services/setbuilder/pool.py` (builders)
- Create: `server/app/services/setbuilder/playlist_url.py` (URL validator/parser)
- Test: `server/tests/test_setbuilder_pool_service.py` (+ URL parser tests)

- [x] **Step 1: Failing tests** — URL parser: accepts `https://open.spotify.com/playlist/<22 base62>`, `https://tidal.com/browse/playlist/<uuid>`, `https://listen.tidal.com/playlist/<uuid>`; recognizes-but-unsupported apple/youtube/soundcloud; rejects http://, non-allowlisted hosts, `javascript:`, userinfo tricks (`https://open.spotify.com@evil.com/...`), path traversal. Event candidates: maps Request rows (excludes REJECTED), tags `request:{id}`; ownership enforced at API layer.
- [x] **Step 2: Implement**
  - `playlist_url.py`: `ParsedPlaylistUrl(provider, playlist_id, supported, message)`; strict full-match regexes per host via `urllib.parse.urlsplit` (scheme must be https, netloc exact-match allowlist, no port/userinfo), ID charset constrained (`[A-Za-z0-9]{16,40}` spotify, uuid for tidal).
  - Builders in `pool.py`: `candidates_from_event(db, user, event_id)` (owner check → None if unowned), `candidates_from_tidal(db, user, playlist_id)` (uses `tidal.get_playlist_tracks` + `tidal._track_to_result`), `candidates_from_beatport(db, user, playlist_id)` (`beatport.get_playlist_tracks` → BeatportSearchResult), `candidate_from_manual(payload)`, `preview_public_playlist(db, user, parsed)` + `candidates_from_public_url(db, user, parsed)` (spotify: spotipy `playlist()` / `playlist_items()` paginated w/ external_ids.isrc; tidal: DJ session).
- [x] **Step 3: Run tests** → PASS.
- [x] **Step 4: Commit** `feat(setbuilder): pool import candidate builders + public-URL validator`

### Task 4: Schemas + API routes (additive) — TDD at API boundary

**Files:**
- Modify (ADDITIVE): `server/app/schemas/setbuilder.py`, `server/app/api/setbuilder.py`
- Test: `server/tests/test_setbuilder_pool_api.py`

Routes (all `get_current_active_user`, owner-or-404, rate-limited):
- `GET /api/setbuilder/sets/{id}/pool` → `PoolState{sources, tracks}` (60/min)
- `GET /api/setbuilder/playlists` → `{tidal_connected, beatport_connected, tidal[], beatport[]}` (20/min)
- `POST .../pool/import/event {event_id}` (10/min)
- `POST .../pool/import/tidal {playlist_id}` / `POST .../pool/import/beatport {playlist_id}` (10/min)
- `POST .../pool/url-preview {url}` → `UrlPreview{provider, supported, name?, owner?, track_count?, message?}` (10/min)
- `POST .../pool/import/url {url}` (10/min)
- `POST .../pool/import/manual {ManualTrackIn}` (30/min)
- `POST .../pool/tracks/remove {track_ids: list[int] (1..500)}` → `PoolMutationResult{removed, pool}` (30/min)
- `DELETE .../pool/sources/{source_id}` → `PoolMutationResult` (30/min)

Import endpoints return `ImportResult{added, deduped, source, pool}` (toast = "N new · M de-duped"). Pydantic constraints on every input field.

- [x] Steps: failing tests (ownership 404s incl. cross-user; event import end-to-end from `test_event` + requests; tidal/beatport mocked imports; dedupe counts across sources; url-preview unsupported + invalid 422; manual import; remove flows count-consistency) → implement → `pytest -q` full suite green → commit `feat(setbuilder): pool import/removal API`.

### Task 5: OpenAPI types + frontend API client

**Files:**
- Run: `cd dashboard && npm run types:export && npm run types:generate`
- Modify (ADDITIVE): `dashboard/lib/api-types.ts` (re-export new schemas), `dashboard/lib/api.ts` (pool methods)

- [x] Add `getPool, getBuilderPlaylists, importPoolEvent, importPoolTidal, importPoolBeatport, previewPoolUrl, importPoolUrl, importPoolManual, removePoolTracks, removePoolSource`. `npx tsc --noEmit` green. Commit `feat(setbuilder): pool API client + generated types`.

### Task 6: Frontend Pool panel + Import modal

**Files:**
- Create: `dashboard/app/(dj)/setbuilder/components/PoolBadges.tsx` (SourceIcon, CamelotBadge via `lib/camelot-colors`, BpmBadge, EnergyMini)
- Create: `dashboard/app/(dj)/setbuilder/components/ImportModal.tsx` (event picker / tidal / beatport playlist pickers / public URL validate→preview→import / manual search via `api.search`)
- Create: `dashboard/app/(dj)/setbuilder/components/PoolPanel.tsx` (header + Add menu, sources accordion w/ filter + hover-×, type tabs w/ counts, search + multi-select toggle, track rows w/ badges + source chip, selection footer, right-click context menu, toast)
- Modify (ADDITIVE): `dashboard/app/(dj)/setbuilder/[setId]/page.tsx` (mount `<PoolPanel setId>` in pool section), `dashboard/app/(dj)/setbuilder/setbuilder.module.css` (append pool classes)

- [x] Implement per design prototype (`~/wrzdjset-design/project/pool-panel.jsx`, `import-modal.jsx`) translated to TS + module CSS + theme tokens; counts always derived from fetched pool state. Commit `feat(setbuilder): pool panel UI — sources accordion, import modal, removal flows`.

### Task 7: Frontend tests

**Files:**
- Create: `dashboard/app/(dj)/setbuilder/components/__tests__/PoolPanel.test.tsx`

- [x] Mock `lib/api`; assert: pool renders tracks w/ source chip + badges; source row click filters; source × calls removePoolSource and updates counts; multi-select select-all/remove calls removePoolTracks; import toast shows "N new · M de-duped". `npm test -- --run` green. Commit `test(setbuilder): pool panel component tests`.

### Task 8: Full CI + finish

- [x] Backend: ruff check/format, bandit, pytest (≥80% cov), alembic upgrade+check. Frontend: lint, tsc, vitest. `git checkout next-env.d.ts` if dirty.
- [x] superpowers:finishing-a-development-branch → option 2: push + PR (`Closes #388`, Design decisions section, migration-slot note).
