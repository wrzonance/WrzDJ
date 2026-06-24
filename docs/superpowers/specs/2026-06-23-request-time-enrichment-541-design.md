# Request-time Enrichment → Global Track Store (#541) — Design Spec

**Date:** 2026-06-23
**Issue:** #541 (child of epic #539; depends on #540 master `tracks` table, now merged)
**Consumes:** #544 Soundcharts audio-features adapter (held in `stash@{0}`)
**Status:** Approved design, pending implementation plan.

## 1. Context

#540 shipped the master `tracks` table + provenance-aware `get_track`/`upsert_track`
service (`app/services/tracks/`), but **no writer is wired to it yet**. Today
`enrich_request_metadata` (`app/services/sync/enrichment_pipeline.py`) fills
`genre`/`bpm`/`musical_key` onto each **`Request` row** — so the same recording
requested at two events is enriched twice, and `energy`/`duration` are never
enriched at request time at all.

This slice makes enrichment **populate the global store once per unique recording
and reuse it** (cache-aside), restores the #544 Soundcharts adapter as the first
audio-features writer, and discharges the concurrent-upsert reconciliation
deferred from #540 (the `NOTE (#540)` at the `db.flush()` in `store.py`).

Per the epic build sequence (master-track-store design §8) this is **step 2**:
enrichment *writes* the store + backfill, dual-writing alongside the legacy
`Request` columns. Read-repoint (the cutover that consumes a `Request.track_id`
FK) is deliberately **out of scope** here — it lands in #542+.

## 2. Goals / non-goals

**Goals**
- One global `tracks` row per unique recording, written at request time, reused
  with **zero** extra API calls on the next request of the same song.
- Capture ISRC during enrichment (currently discovered then discarded) so a
  request and a later pool-import of the same recording collapse to one row.
- Add the energy/audio-features cascade hook (Soundcharts primary, dark by
  default) — energy populates when the gate is enabled; otherwise backfills later.
- Discharge the deferred concurrent-upsert `IntegrityError` reconciliation.
- Backfill existing `Request` metadata into the store, idempotently.

**Non-goals (now)**
- No `Request.track_id` FK and no read-repoint — readers still read `Request`
  columns (deferred to #542+).
- No TTL/re-enrichment (cache forever; `provenance.fetched_at` enables it later).
- No ReccoBeats fallback (the cascade leaves the hook; #544 future path).
- No schema migration in either PR (all changes are code + a script).

## 3. Delivery — two sequential PRs

### PR1 — Foundation (`feat/541-enrichment-store-foundation`)
No enrichment behavior change; both pieces are foundational and green.

1. **`upsert_track` IntegrityError reconciliation** (spec §5 of the master design;
   the deferred `NOTE (#540)`). Wrap the insert path in a `Session.begin_nested()`
   savepoint. On `IntegrityError` from `uq_tracks_isrc`/`uq_tracks_signature` (a
   concurrent caller inserted the same identity first), roll back **only the
   savepoint**, re-read the now-existing row by `isrc`→`signature`, and re-apply
   the precedence-guarded merge onto it. Net: exactly one row, no lost writes.
2. **Restore the #544 Soundcharts adapter** from `stash@{0}`:
   `soundcharts.py:get_song_features_by_isrc`, the `SoundchartsAudioFeatures`
   dataclass, energy/ISRC normalizers, the `soundcharts_audio_features_enabled`
   config gate (**dark by default**), `.env.example` docs, and `test_soundcharts.py`.
   Additive and unit-tested; dead until PR2 wires it.

### PR2 — #541 core (`feat/541-request-time-enrichment`)
The demonstrable change: enrichment writes + reuses the store.

3. Rewire `enrich_request_metadata` to **cache-aside dual-write** (§4).
4. One-shot idempotent **backfill script** (§6).

## 4. Data flow (PR2)

```
request submitted → BackgroundTask: enrich_request_metadata(db, request_id)
  sig = dedupe_signature(artist, song_title)            # same helper pool import uses
  cached = get_track(db, signature=sig)
    ├─ complete? → copy genre/bpm/musical_key onto Request, return     ← ZERO API calls (dedupe win)
    └─ miss/partial → existing Beatport/Tidal/Spotify/MusicBrainz lookups,
                       now CAPTURING isrc + per-field source into an accumulator
        [gate ON + isrc] soundcharts.get_song_features_by_isrc(isrc)
                          → energy/danceability/valence/explicit/…
        upsert_track(identity{sig, isrc}, values, sources, fetched_at)  ← store = source of truth
        write genre/bpm/musical_key onto Request                         ← dual-write for current UI
  db.commit()
```

- **Completeness gate for the short-circuit:** the same fields the current early
  return checks — `genre AND bpm AND musical_key` present on the store row → skip
  all providers and copy down. (`duration`/`energy` do not gate the skip; they are
  best-effort extras and backfill independently.)
- **Cache forever:** no freshness check; a complete row is always reused.

## 5. Components & key decisions

1. **Provenance threading.** `_apply_enrichment_result` currently sets
   `request.bpm/key/genre` with no source record. Introduce a small accumulator
   `resolved: dict[field → (value, source)]` populated alongside the Request
   writes; `values`/`sources` for `upsert_track` come directly from it — no
   post-hoc source guessing. Source labels map provider → ladder name:
   Beatport→`beatport`, Tidal→`tidal`, MusicBrainz→`musicbrainz`,
   Soundcharts→`soundcharts`, LLM→`llm`.
2. **Capture ISRC.** `_get_isrc_from_spotify` (and ISRC on Tidal/Beatport hits)
   feeds `TrackIdentity.isrc` rather than being discarded after the Tidal lookup.
3. **New `legacy` provenance source @ precedence 30** (below `community` 40) in
   `SOURCE_PRECEDENCE`. The backfill copies existing `Request` columns that record
   no original source; attributing them `legacy` (lowest) guarantees any real
   later enrichment overrides them. `KNOWN_SOURCES` derives from the dict, so the
   new source is automatically accepted by `upsert_track`'s boundary validation.
4. **Energy gate.** Soundcharts is called only when
   `settings.soundcharts_audio_features_enabled` is true **and** an ISRC is in
   hand **and** the store row lacks energy. Off by default → no-op → energy
   backfills via the cascade later. This keeps quota and caching/redistribution
   licensing concerns dark until validated (#544 gate).

## 6. Backfill script

`app/scripts/backfill_tracks.py`, runnable as `python -m app.scripts.backfill_tracks`.

- Walk `Request` rows with any of `genre`/`bpm`/`musical_key` set.
- For each, `sig = dedupe_signature(artist, song_title)`; `upsert_track` the
  present fields with `source="legacy"`, `fetched_at = request.updated_at`.
- **Idempotent:** sig-dedup + precedence guard make re-runs no-ops (legacy never
  downgrades an existing legacy/higher value).
- Logs counts (rows scanned, tracks upserted) and never raises on a single bad row.

## 7. Error handling

- Enrichment is best-effort on a `BackgroundTask`; it never blocks a guest request
  (existing pattern in `events.py`/`requests.py`/`collect.py`).
- Per-source `try/except` already isolates provider failures. A Soundcharts/quota
  failure leaves `energy` null (backfills later); other resolved fields still
  upsert.
- The `upsert_track` call is wrapped so an unexpected store error logs and still
  lets the Request's own dual-write + commit land — the store is strictly
  additive and must never regress the existing request flow.
- The concurrent-insert race is absorbed inside `upsert_track` (PR1).

## 8. Testing

**PR1**
- Reconciliation: monkeypatch `get_track` to return `None` on the first call
  (simulating the TOCTOU window) while a conflicting row is already committed;
  assert the insert hits `IntegrityError`, reconciles onto the existing row, ends
  with exactly one row and the merged (precedence-correct) values — no data loss.
- Adapter: `test_soundcharts.py` rides in with the stash (response parsing,
  energy 0–1→0–10 normalization, ISRC normalization, quota-saver single-call).

**PR2**
- **Headline regression (AC):** request song X at event A → enrich → `tracks` row
  exists; request X at event B → enrich → `get_track` hit → assert mocked
  Beatport/Tidal/MusicBrainz are **not called** and Request B is populated from
  the store. Pins "enrich once, reuse everywhere."
- Provenance recorded per field with the right source.
- Dual-write: `Request.genre/bpm/musical_key` still populated (current behavior
  preserved) **and** the `tracks` row populated.
- Energy gate: off → Soundcharts not called, `energy` null; on + ISRC → adapter
  called (mocked), `energy` written with `source="soundcharts"`.
- Backfill: seed Requests → run → `tracks` upserted with `source="legacy"`;
  re-run is a no-op (idempotent).
- Coverage held ≥85%; `alembic check` clean (no migration in either PR).

## 9. Open questions / future

- `Request.track_id` FK + read-repoint — #542+ (the cutover that consumes the store).
- ReccoBeats fallback + bulk backfill (quota path) — hook left in the cascade (#544).
- Provenance-driven re-enrichment/TTL — enabled by `fetched_at`, deferred.
- Soundcharts caching/redistribution licensing — confirm before enabling the gate
  in prod; feature stays dark by default until then.
