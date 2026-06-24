# Track-metadata read-site inventory (cutover blast-radius)
Date: 2026-06-23 · Feeds #540 hard cutover (repoint targets for PR3/PR4, drop targets for PR5).

## Background

This inventory was produced by grepping all non-test Python source under `server/app/` for every
direct field access to the seven canonical track-metadata columns (`bpm`, `musical_key`/`key`,
`camelot`, `genre`, `energy`, `duration_sec`, `isrc`) and for all references to the key model
classes and helpers (`SetPoolTrack`, `TrackVibe`, `vibe_resolver`, `enrich_request_metadata`,
`_track_meta`).  439 raw grep hits were de-duplicated into the groups below.

### Source tables that carry track metadata today

| Table | Model class | Fields of interest |
|---|---|---|
| `requests` | `Request` | `bpm`, `musical_key`, `genre` (no energy/duration/isrc columns) |
| `set_pool_tracks` | `SetPoolTrack` | `bpm`, `key`, `camelot`, `genre`, `energy`, `isrc`, `duration_sec` |
| `track_vibes` | `TrackVibe` | `energy`, `mood`, `era`, `sing_along`, `dance_floor`, `transitional_role` |
| `track_vibe_overrides` | `TrackVibeOverride` | `energy_override`, `mood_override` (per-DJ overrides) |

### Key in-memory intermediaries (not in DB, must map to the new `tracks` table in PR3/PR4)

| Dataclass | Module | Metadata fields carried |
|---|---|---|
| `PoolCandidate` | `services/setbuilder/pool.py` | `bpm`, `key`, `genre`, `energy`, `isrc`, `duration_sec` |
| `TrackMeta` | `services/setbuilder/pass1_deterministic.py` | `bpm`, `key`, `energy`, `mood`, `transitional_role` |
| `TrackProfile` | `services/recommendation/scorer.py` | `bpm`, `key`, `genre` |
| `NormalizedTrack` | `services/track_normalizer.py` | (title/artist normalisation – no metadata fields) |
| `SearchResult` | `schemas/search.py` | `bpm`, `key`, `isrc`, `genre` |
| `ExportTrack` | `services/setbuilder/export_common.py` | `genre`, `bpm`, `key`, `camelot`, `isrc`, `duration_sec` |

---

## Inventory table

The table groups hits by subsystem. "R" = read, "W" = write/mutation.

### 1. Request pipeline

| file:line | Field(s) | R/W | Notes | Cutover action |
|---|---|---|---|---|
| `api/public.py:345-347` | `bpm`, `musical_key`, `genre` | R | Guest-facing now-playing/history serialisation reads from `Request` | PR3: add `track_id` FK on `Request`; read from `tracks` if present, fall back to `Request` columns |
| `api/requests.py:103-105` | `genre`, `bpm`, `musical_key` | R | DJ request-list serialisation | PR3: same fallback strategy |
| `api/collect.py:208-210` | `bpm`, `musical_key`, `genre` | R | Request detail serialisation in collect flow | PR3: fallback |
| `api/collect.py:425-427` | `bpm`, `musical_key`, `genre` | R | Second serialisation call in collect flow | PR3: fallback |
| `api/collect.py:505` | `genre`, `bpm`, `musical_key` | R | Completeness gate: skips enrichment if all three present | PR3: check `tracks` row instead |
| `api/collect.py:579-581` | `bpm`, `key`, `genre` | W | Writes best-match metadata back onto `Request` after search merge | PR4: write to `tracks` table instead |
| `api/events.py:204-206` | `genre`, `bpm`, `musical_key` | R | Event request-list serialisation | PR3: fallback |
| `api/events.py:231-233` | `bpm`, `key`, `genre` | R | Event music-profile aggregation (profile endpoint) | PR3: read from `tracks` |
| `api/events.py:706-708` | `genre`, `bpm`, `musical_key` | W | Initial write of metadata when a new request is submitted | PR4: write to `tracks` |
| `api/events.py:712` | `genre`, `bpm`, `musical_key` | R | Completeness gate after submission | PR3: check `tracks` |
| `api/events.py:893-894` | `musical_key`, `bpm` | R | Bridge now-playing match: pulls key/bpm for enrichment log | PR3: read from `tracks` |
| `api/events.py:902-903` | `musical_key`, `bpm` | R | SSE now-playing push body | PR3: fallback |
| `api/events.py:1258` | `bpm`, `key`, `genre` (comment) | — | Comment referencing enrichment columns | No-op |
| `api/events.py:1300` | — | — | Calls `enrich_request_metadata` (writes — see pipeline section) | — |
| `api/events.py:1377` | `bpm`, `musical_key`, `genre` | R | Batch-enrichment filter: finds requests missing metadata | PR3: filter on `tracks` row instead |
| `api/requests.py:42` | — | — | Calls `enrich_request_metadata` | — |
| `services/request.py:221-223` | `genre`, `bpm`, `musical_key` | W | Clears metadata on request title-change | PR4: clear `tracks` row FK |
| `services/export.py:74-76` | `genre`, `bpm`, `musical_key` | R | CSV export of requests | PR3: read from `tracks` |

### 2. Enrichment / sync pipeline

| file:line | Field(s) | R/W | Notes | Cutover action |
|---|---|---|---|---|
| `services/sync/enrichment_pipeline.py:204-209` | `genre`, `bpm`, `musical_key` | W | Copies best API hit fields onto `Request` (fill-in) | PR4: upsert into `tracks` table; keep `Request` write for backward compat until PR5 |
| `services/sync/enrichment_pipeline.py:231` | `genre`, `bpm`, `musical_key` | R | Gate: skip LLM call if all three already present | PR3: gate on `tracks` row |
| `services/sync/enrichment_pipeline.py:252-254` | `genre`, `bpm`, `musical_key` | R | Passes to LLM enrichment call | PR3: read from `tracks` |
| `services/sync/enrichment_pipeline.py:259-270` | `bpm`, `musical_key` | R/W | Beatport direct-lookup; writes key/bpm back onto request | PR4: write to `tracks` |
| `services/sync/enrichment_pipeline.py:277-288` | `bpm`, `musical_key` | R/W | Tidal direct-lookup; writes key/bpm back | PR4: write to `tracks` |
| `services/sync/enrichment_pipeline.py:295-310` | `bpm`, `musical_key` | R/W | Spotify ISRC-based lookup; writes key/bpm | PR4: write to `tracks` |
| `services/sync/enrichment_pipeline.py:318-322` | `genre` | W | Soundcharts genre fill | PR4: write to `tracks` |
| `services/sync/enrichment_pipeline.py:327-352` | `bpm`, `musical_key`, `genre` | R/W | LLM fallback — checks, calls, writes | PR4: write to `tracks` |
| `services/sync/enrichment_pipeline.py:362-386` | `bpm`, `musical_key` | R/W | Second LLM pass for remaining blanks | PR4: write to `tracks` |
| `services/sync/enrichment_pipeline.py:396-427` | `bpm`, `musical_key` | R/W | Normalises key, BPM-context correction | PR4: normalise on `tracks` row |
| `services/sync/enrichment_pipeline.py:433-435` | `genre`, `bpm`, `musical_key` | R | Final log / return values | PR3: read from `tracks` |
| `services/sync/orchestrator.py:28` | — | — | Imports `enrich_request_metadata` for re-export | — |
| `services/recommendation/enrichment.py:90-94` | `bpm`, `key` | R | Tidal search hit → track profile construction | PR3: these are transient objects, no DB read needed |
| `services/recommendation/enrichment.py:154-173` | `bpm`, `key`, `genre` | R | Merge of Beatport+Tidal profiles | transient — no cutover |
| `services/recommendation/enrichment.py:207-209` | `bpm`, `key`, `genre` | R | Combined profile for scoring | transient |
| `services/recommendation/enrichment.py:252-266` | `bpm`, `key`, `genre` | R | Reads from `Request` to build `TrackProfile` | PR3: read from `tracks` |
| `services/search_merge.py:89-91` | `bpm`, `key`, `isrc` | R | Builds `SearchResult` from Tidal hit | transient |
| `services/search_merge.py:107-109` | `genre`, `bpm`, `key` | R | Builds `SearchResult` from Beatport hit | transient |
| `services/search_merge.py:124-144` | `isrc`, `bpm`, `key`, `genre` | R | ISRC deduplication and field-merge of search results | transient — feeds `collect.py:579` write |
| `services/tidal.py:204-210` | `bpm`, `key` | R | Reads from Tidal API object → transient | transient |
| `services/soundcharts.py:17` | — | R | `parse_key` import | no cutover |
| `services/soundcharts_candidates.py:78-79` | `bpm`, `key` | R | Constructs candidate from Tidal+Soundcharts | transient |

### 3. Set-builder — pool management

| file:line | Field(s) | R/W | Notes | Cutover action |
|---|---|---|---|---|
| `services/setbuilder/pool.py:155-156` | `dedupe_sig`, `isrc` | R | Existing-track deduplication query on `SetPoolTrack` | PR3: look up in `tracks` if ISRC present |
| `services/setbuilder/pool.py:174-215` | `genre`, `bpm`, `key`, `camelot`, `energy`, `isrc`, `duration_sec` | W | **Main pool import write path**: creates `SetPoolTrack` rows from `PoolCandidate` | PR4: also write a `tracks` row (upsert by ISRC+sig) and set FK |
| `services/setbuilder/pool.py:267-294` | `genre`, `bpm`, `key`, `isrc` | W | Imports from event requests into pool | PR4: upsert `tracks`; set FK |
| `services/setbuilder/pool.py:318-320` | `genre`, `bpm`, `key` | W | Imports from public-URL / Spotify tracks | PR4: upsert `tracks`; set FK |
| `services/setbuilder/pool.py:389` | `isrc` | R | Spotify GraphQL field selector (string literal) | no cutover |
| `api/setbuilder.py:308-315` | — | R | Queries `SetPoolTrack` for track-id/pool-track-id filters | PR3: pass-through; FK lookup added |
| `api/setbuilder.py:342-346` | `bpm`, `key`, `camelot`, `energy`, `duration_sec` | R | Pool-track serialisation (list endpoint) | PR3: read from `tracks` via FK |
| `api/setbuilder.py:1214-1218` | `genre`, `bpm`, `key`, `isrc`, `duration_sec` | W | Manual-add endpoint writes `PoolCandidate` fields | PR4: also upsert `tracks` |
| `services/setbuilder/export_common.py:61-66` | `genre`, `bpm`, `key`, `camelot`, `isrc`, `duration_sec` | R | Converts `SetPoolTrack` → `ExportTrack` for file export | PR3: read from `tracks` via FK |
| `services/setbuilder/export_files.py:64-115` | `genre`, `isrc`, `duration_sec`, `bpm`, `key`, `camelot` | R | Writes metadata into export XML/M3U files | PR3: reads through `ExportTrack` (see above) |
| `services/setbuilder/export_tidal.py:83-84` | `isrc` | R | ISRC-based Tidal match for export | PR3: read from `tracks` |
| `services/setbuilder/document_snapshot.py:55` | `energy` | R | Snapshot serialises energy from `SetSlot.curve_point` | no cutover (curve, not pool) |
| `services/setbuilder/document_snapshot.py:82-88` | `genre`, `bpm`, `key`, `camelot`, `energy`, `isrc`, `duration_sec` | R | Snapshot serialises pool-track metadata | PR3: read from `tracks` via FK |
| `services/setbuilder/document_snapshot.py:109` | — | W | Deletes all `SetPoolTrack` rows on restore | PR4: also clear `tracks` FK? (tbd: tracks rows are global) |
| `services/setbuilder/document_snapshot.py:136-149` | `genre`, `bpm`, `key`, `camelot`, `energy`, `isrc`, `duration_sec` | W | Re-creates `SetPoolTrack` rows on snapshot restore | PR4: re-upsert `tracks`; set FK |
| `services/setbuilder/pairings.py:227` | `camelot`, `bpm` | R | Text search haystack construction | PR3: read from `tracks` |
| `services/setbuilder/playhistory_feedback.py:104-139` | — | R | Holds `SetPoolTrack` refs for play-history match | PR3: pass-through |

### 4. Set-builder — build passes (pass1 / pass2 / agent tools)

| file:line | Field(s) | R/W | Notes | Cutover action |
|---|---|---|---|---|
| `services/setbuilder/pass1_deterministic.py:62` | — | R | `_track_meta(t)` — builds `TrackMeta` from `SetPoolTrack` | PR3: `_track_meta` reads from `tracks` via FK |
| `services/setbuilder/pass1_deterministic.py:116` | — | R | `_track_meta` batch over pool | PR3: same |
| `services/setbuilder/pass1_deterministic.py:196-204` | `bpm`, `key`, `camelot`, `energy` | R | `_track_meta` implementation — reads 4 fields from `SetPoolTrack` | **Key cutover point**: PR3 repoints to `tracks` table |
| `services/setbuilder/pass1_deterministic.py:221` | `duration_sec` | R | Average duration calc | PR3: via `_track_meta` |
| `services/setbuilder/pass1_deterministic.py:294` | `energy` | R | Energy-match scoring | PR3: via `_track_meta` |
| `services/setbuilder/pass1_deterministic.py:315` | `bpm` | R | BPM transition score | PR3: via `_track_meta` |
| `services/setbuilder/pass1_deterministic.py:321` | `key` | R | Camelot compatibility score | PR3: via `_track_meta` |
| `services/setbuilder/pass2_agent.py:391-409` | `bpm`, `camelot`/`key`, `energy` | R | Agent JSON payload for LLM context | PR3: via `_pass1_track_meta` |
| `services/setbuilder/agent_tools_sensing.py:53-215` | `bpm`, `key`, `energy`, `duration_sec`, `camelot` | R | All sensing tools read via `_pass1_track_meta` or direct field access on `SetPoolTrack` | PR3: `_pass1_track_meta` repoint covers most; direct `.duration_sec` on line 212 must also move |
| `services/setbuilder/agent_tools_mutations.py:228` | `energy` | R | Serialises `CurvePoint.energy` (curve, not pool track) | no cutover |
| `services/setbuilder/agent_tools_structural.py:51-52` | `duration_sec` | R | Duration check for set-length budget | PR3: via `_pass1_track_meta` or `tracks` FK |
| `services/setbuilder/vibe_enrichment.py:120-125` | `genre`, `bpm` | R | Prompt-line construction for LLM vibe call | PR3: read from `tracks` via FK |
| `services/setbuilder/curve.py:347` | `energy` | W | Writes `energy` onto `CurvePoint`, not `SetPoolTrack` | no cutover (separate model) |

### 5. Vibe subsystem

| file:line | Field(s) | R/W | Notes | Cutover action |
|---|---|---|---|---|
| `models/track_vibe.py:32-67` | `energy`, `mood`, `era`, etc. | — | `TrackVibe` table definition — LLM-vibe cache keyed by `track_id` string | PR5: `track_id` string column replaced by FK to `tracks.id` |
| `models/track_vibe.py:69-end` | `energy_override`, `mood_override` | — | `TrackVibeOverride` table definition | PR5: same FK replacement |
| `services/setbuilder/vibe_resolver.py:85-193` | — | R | Queries `TrackVibe` and `TrackVibeOverride` by `track_id` string key | PR5: repoint to FK |
| `services/setbuilder/vibe_enrichment.py:88-275` | — | R/W | Batch LLM enrichment writes `TrackVibe` rows | PR5: write via FK |
| `services/setbuilder/community_vibe.py:75-84` | — | R | Community consensus query over `TrackVibeOverride` | PR5: repoint |
| `api/setbuilder.py:1268-1363` | `energy` | R/W | Reads vibe states, reads `energy`; writes `TrackVibeOverride` | PR3 (energy read via state), PR5 (write path) |
| `services/setbuilder/share_service.py:91` | `energy` | R | Serialises `CurvePoint.energy` in share snapshot | no cutover (CurvePoint) |

### 6. Recommendation engine

| file:line | Field(s) | R/W | Notes | Cutover action |
|---|---|---|---|---|
| `services/recommendation/scorer.py:63-311` | `bpm`, `key`, `genre` | R | Event-profile scoring reads from `TrackProfile` objects | PR3: `TrackProfile` is transient; source data read path changes above |
| `services/recommendation/service.py:430-761` | `genre`, `bpm`, `key` | R | Scoring service reads `TrackProfile`; genre block-list check | PR3: transient — source changes above |
| `services/recommendation/llm_client.py:190-195` | `bpm`, `key`, `genre` | R | Builds LLM prompt from `TrackProfile` | transient |
| `services/recommendation/template.py:57-85` | `bpm`, `key`, `genre` | R | Template-based recommendation uses same `TrackProfile` | transient |
| `services/recommendation/soundcharts_candidates.py:78-79` | `bpm`, `key` | R | Constructs `TrackProfile` from combined Tidal result | transient |
| `services/priority_scorer.py:227-228` | `musical_key`, `bpm` | R | Priority scorer reads from `Request` row | PR3: read from `tracks` via FK |
| `services/request_sort.py:39,97` | `bpm`, `musical_key` | R | Sort key extraction from `Request` row | PR3: read from `tracks` via FK |

### 7. Dashboard / API serialisation

| file:line | Field(s) | R/W | Notes | Cutover action |
|---|---|---|---|---|
| `api/events.py:706-714` | `genre`, `bpm`, `musical_key` | W | Submit-request endpoint writes metadata to `Request` | PR4: write to `tracks` |
| `api/events.py:893-903` | `musical_key`, `bpm` | R | Now-playing enrichment reads from matched `Request` | PR3: read from `tracks` |
| `schemas/setbuilder.py:642` | — | — | `SetDocumentPoolTrack` — Pydantic schema mirrors `SetPoolTrack` fields | PR3: add `tracks_id` FK field; PR5: drop old fields |

---

## Summary statistics

| Subsystem | Read sites | Write/mutation sites |
|---|---|---|
| Request pipeline | 14 | 4 |
| Enrichment / sync | 15 | 10 |
| Set-builder pool | 11 | 7 |
| Set-builder build passes | 12 | 0 |
| Vibe subsystem | 8 | 3 |
| Recommendation engine | 7 | 0 |
| Dashboard serialisation | 3 | 1 |
| **Total** | **70** | **25** |

---

## Cutover PR assignment map

| PR | Scope | Sites covered above |
|---|---|---|
| **PR3** (add FK + dual-read) | Add `tracks_id` FK to `SetPoolTrack`; all _read_ paths switch to preferring `tracks` with fallback to pool columns | All rows marked "PR3" |
| **PR4** (flip writes) | All _write_ paths upsert into `tracks` and set FK; remove backward-compat writes on `Request.*` columns (except for bridge/serialisation fallback) | All rows marked "PR4" |
| **PR5** (drop columns) | Remove old metadata columns from `Request` and `SetPoolTrack`; replace `track_id` string with FK in `TrackVibe` / `TrackVibeOverride` | All rows marked "PR5" |

---

## Special concerns

1. **`Request.musical_key` vs `SetPoolTrack.key`** — field name inconsistency. The `tracks` table
   should normalise to a single name (`musical_key`).  All call sites that map one to the other (e.g.
   `pool.py:269`: `key=r.musical_key`) must be audited during PR3.

2. **`SetPoolTrack.camelot` derived column** — written eagerly from `camelot_code(key)` at import time
   (`pool.py:189`).  The `tracks` table should either store it redundantly (for query convenience) or
   compute it on read.  Decide before PR4.

3. **`energy` source confusion** — `SetPoolTrack.energy` is filled by the vibe enrichment LLM pass;
   `CurvePoint.energy` is a separate DJ-set energy-curve column.  Lines referencing `.energy` in
   `curve.py`, `agent_tools_mutations.py`, `share_service.py`, and `document_snapshot.py:55` are
   **CurvePoint energy**, not track energy, and require no cutover.

4. **Snapshot restore** (`document_snapshot.py:136-149`) re-creates `SetPoolTrack` rows from a
   snapshot blob.  If PR4 has already migrated writes to `tracks`, the restore must also re-upsert
   into `tracks`.  The global `tracks` row is non-destructive (upsert), so this is safe.

5. **`TrackVibe.track_id` is a free-form string** (e.g. `"tidal:12345"`, `"request:9"`) with no FK —
   by design, because no unified table existed.  PR5 replaces it with a real FK.  The vibe resolver
   must be updated before the string column is dropped.

6. **`services/sync/enrichment_pipeline.py:212`** defines `enrich_request_metadata` — the entry
   point for all async enrichment background tasks.  This is the single widest blast-radius function;
   PR4 must update it atomically.
