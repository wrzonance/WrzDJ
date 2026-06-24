# Master Song Store + Hard Cutover — Design Spec

**Date:** 2026-06-23
**Issues:** #539 (epic) · #540 (Task 0 — this table) · absorbs #541 / #542 / #543 · #544 (first audio-features writer)
**Status:** Approved design, pending implementation plan.

## 1. Context & decision

WrzDJ has **no unified track table** (a deliberate prior stance: `set_pool.py` / `track_vibe.py` use free-form namespaced IDs, no FK). The costs:

- The same recording is enriched repeatedly — `enrich_request_metadata` writes bpm/key/genre onto each `Request` row, so the same song requested at two events is enriched twice.
- There is no single place a track's known bpm/key/genre/duration/energy lives, recallable across DJs/events/builder pools.
- **Dead-energy bug (#543):** pass-1 reads `energy` off `SetPoolTrack.energy`, which is structurally always `None` — energy contributes nothing to set sequencing.

**Decision (maintainer, 2026-06-23):** introduce a **master `tracks` table as the single source of truth** for song data, recallable by **any DJ, any event, and any WrzDJSet builder request**, and **hard-cut** all readers/writers over to it — retiring the redundant inline enrichment columns on `Request` / `SetPoolTrack`.

This **overrides the epic's "never big-bang / one-surface-at-a-time" rule**, which exists to protect *other DJs' in-flight work* in a multi-tenant deployment. At **solo / private-VPS scale** that protection is moot, and a permanent dual-source-of-truth is more debt than it's worth. The cutover **absorbs** the read-migration work of #541/#542/#543 and **fixes #543 for free**.

"Hard cutover" = the **end state** (no dual source of truth), **not** one reckless commit — it is sequenced into green-at-each-step PRs (§8).

## 2. Goals / non-goals

**Goals**
- One global row per unique recording, written once, reused everywhere (zero re-enrichment per unique track).
- ISRC-first identity with a universal signature fallback so *every* track gets a row.
- Typed, queryable value columns; compact per-field provenance.
- All enrichment readers consume the master table; redundant inline columns dropped.

**Non-goals (now)**
- No TTL / re-enrichment job (cache forever; `provenance.fetched_at` enables it later).
- No ReccoBeats fallback wiring yet (the cascade leaves a hook; ReccoBeats is the future quota/backfill path).
- No bulk catalog backfill tooling (Soundcharts has no batch endpoint; steady-state request-time enrichment is incremental — see #544 comment).

## 3. Schema — `tracks`

**Identity & keys**
| Column | Type | Notes |
|---|---|---|
| `id` | int PK | surrogate |
| `isrc` | String(15), unique, nullable, indexed | normalized upper / no-hyphens |
| `signature` | String(64), unique, NOT NULL, indexed | `dedupe_signature(artist, title)` |
| `title`, `artist` | String(255), NOT NULL | canonical display |
| `soundcharts_uuid` | String(36), nullable | cached resolve |

**Value columns (typed, directly queryable)**
| Column | Type | Scale |
|---|---|---|
| `bpm` | Float | |
| `musical_key` | String(20) | human "G Major" (via `pitch_class_to_key_string`) |
| `camelot` | String(3) | |
| `genre` | String(100) | single primary genre (first from the highest-precedence genre source: MusicBrainz artist genre, else Soundcharts' first sub-genre) |
| `duration_sec` | Integer | |
| `energy` | Integer | **0–10** (house scale; resolved best per cascade) |
| `danceability`, `valence`, `acousticness`, `instrumentalness`, `speechiness`, `liveness` | Float | native 0–1 |
| `loudness_db` | Float | dB |
| `time_signature` | Integer | |
| `explicit` | Boolean | clean-set pre-filter |
| `artwork_url` | String(500) | |

**Provenance & timestamps**
| Column | Type | Notes |
|---|---|---|
| `provenance` | JSON | `{field: {source, fetched_at}}`; write-path validated by Pydantic |
| `created_at`, `updated_at` | DateTime | `utcnow` default (matches house pattern) |

Value queries (e.g. "energy of ISRC X") are plain indexed column lookups — the JSON is never in that path.

## 4. Identity & dedup

- Lookup order: **ISRC (if present) → signature**. `signature = dedupe_signature(artist, title)` (existing SHA256[:32], reused).
- **ISRC backfill:** when an enrichment arrives with an ISRC for a track that currently exists only by signature, set `isrc` on that row (collapses to one row).
- Same recording across two platform IDs but one ISRC → **one row** (unit-tested).

## 5. Services API — `app/services/tracks/`

```python
def get_track(db, *, isrc: str | None = None, signature: str | None = None) -> Track | None
def upsert_track(db, *, identity: TrackIdentity, values: dict, provenance: dict[str, FieldProvenance]) -> Track
```

- `TrackIdentity` carries title, artist, isrc?, signature, soundcharts_uuid?.
- Provenance shape (validated at boundary):
  ```python
  class FieldProvenance(BaseModel):
      source: str       # soundcharts|beatport|tidal|musicbrainz|lexicon|community|llm|manual
      fetched_at: datetime
  ```
- **Per-field precedence ("don't downgrade"):** `upsert_track` overwrites a field only when the new source's precedence ≥ the existing field's source precedence (or the field is null). Precedence (higher wins):
  `manual/own-override 100 · lexicon(measured) 90 · soundcharts/beatport/tidal/musicbrainz 50 · community 40 · llm(inferred) 10`.
- **Concurrency:** unique constraints on `isrc`/`signature`; on IntegrityError, re-read and merge (mirrors `uq_set_pool_track_sig`).

## 6. Data flow — cache-aside populate-and-reuse

```
enrich track (request submit, or pool import)
   compute signature (+ ISRC if known)
        │
   get_track() ── hit & complete ──▶ REUSE — zero API calls   ← quota defense
        │ miss / missing fields
        ▼
   call only the needed sources:
     MusicBrainz → genre · Beatport/Tidal → bpm/key · Soundcharts → audio-features (by ISRC)
        ▼
   upsert_track(values, provenance)   (precedence-guarded)
```

**Energy cascade → `energy` column:** Soundcharts measured (primary) → Lexicon override (#526) → LLM-inferred (#391, via `TrackVibe`). Resolved best written to `tracks.energy` with `provenance.energy.source`. `TrackVibe`/`TrackVibeOverride` remain the vote/override layer feeding the column. The Soundcharts adapter (`app/services/soundcharts.py:get_song_features_by_isrc`, already built on `feat/544-soundcharts-audio-features`) is the first audio-features writer.

## 7. Cutover

- **FK linkage:** nullable `Request.track_id` and `SetPoolTrack.track_id` → `tracks.id`, set by enrichment.
- **Readers repointed** to read enrichment from the master table: request pipeline, setbuilder pool, pass-1 `_track_meta` (fixes #543), `vibe_resolver`, recommendation engine.
- **Columns dropped** after readers move: `Request.genre/bpm/musical_key`; `SetPoolTrack.genre/bpm/key/camelot/energy/isrc/duration_sec`. Each table keeps its membership/display fields (`title`, `artist`, `dedupe_sig`/`dedupe_key`, source linkage).
- **Read-site inventory is a required deliverable** (#540 AC): exhaustively enumerate every read/write of `bpm/key/musical_key/camelot/genre/energy/duration_sec/isrc` on `Request`, `SetPoolTrack`, `TrackVibe`/`vibe_resolver`, recommendation, dashboard — the cutover must hit every one.

## 8. Build sequence (green at every step)

0. **(done, held)** Soundcharts audio-features adapter — `feat/544-soundcharts-audio-features` (#544).
1. `tracks` table + migration + `tracks` service (get/upsert + provenance + precedence). Additive, no readers changed. (#540 core)
2. Enrichment **writes** the store (cache-aside populate-and-reuse) + **backfill** existing data; dual-write alongside legacy columns. (#541)
3. Repoint **setbuilder pool + pass-1 `_track_meta`** reads → store; characterization tests; **#543 regression** (energy changes ordering). (#542/#543)
4. Repoint **request pipeline + recommendation** reads → store.
5. **Drop** redundant inline enrichment columns (final cutover); migration.

## 9. Error handling

- Enrichment is best-effort, **never blocks a guest request**. Provider/quota failure → `upsert_track` writes resolved fields only; unresolved stay null (no provenance entry); row still exists by identity.
- No ISRC → signature fallback always yields a row.
- Provenance validated by Pydantic before write; malformed rejected.
- Nullable `track_id` FK → un-resolved Request/pool track behaves like today's un-enriched state, never a crash.

## 10. Testing

- `tracks` service: ISRC-first/signature-fallback; insert/update/provenance-merge; ISRC backfill; precedence (no downgrade); identity dedup.
- Cache-aside reuse: 2nd enrichment of a known track → **zero** provider calls.
- Characterization tests around each repointed reader (identical output pre/post cutover).
- Migration up/down clean; `alembic check` passes.
- #543 regression pinned (non-null energy changes pass-1 candidate ordering).
- Repo coverage gate (85%) held throughout.

## 11. Open questions / future

- ReccoBeats fallback + batch backfill (quota path) — hook left in the cascade.
- Lexicon measured-energy override (#526) — slots in at precedence 90.
- Provenance-driven re-enrichment/TTL job — enabled by `fetched_at`, deferred.
- Soundcharts caching/redistribution licensing — confirm API agreement before enabling in prod (#544 gate); feature stays dark by default until then.
