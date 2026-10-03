# Implementation plan — selected Lexicon tracks into a WrzDJSet pool

**Parent research:** `docs/superpowers/specs/2026-10-03-issue-526-lexicondj-design.md`  
**Related roadmap:** #442 Family 4  
**Scope:** Phase A only. Do not implement measured-energy matching while Lexicon's documented Track schema lacks ISRC and analyzer-origin fields.

## Goal and invariants

Let a DJ explicitly select Lexicon tracks and add them to one of their own WrzDJSet pools through the Lexicon plugin. Every imported row is owned by the destination set; the plugin cannot select another owner, create a guest request, or write shared measured-energy values.

Invariants:

1. The endpoint derives the actor from a valid, revocable pairing credential; request JSON never supplies an authoritative owner ID.
2. The set belongs to the authenticated actor.
3. Only a bounded, validated track payload is accepted. Do not persist Lexicon-local IDs as global identities, infer ISRC, or import Energy in this phase.
4. Import is additive and deduped through current pool semantics. The request table and shared `Track.energy` remain untouched.
5. Plugin code calls only the configured WrzDJ HTTPS API host and reads selected Lexicon tracks only.
6. Plugin/backend contract versions are checked before import; incompatibility returns a safe, actionable error.

## Data shapes and interfaces

Proposed plugin payload (exact field list should match current `PoolCandidate` and product import needs):

```json
{
  "contract_version": 1,
  "tracks": [
    {
      "title": "Track title",
      "artist": "Artist name",
      "album": "Optional album",
      "genre": "Optional genre",
      "bpm": 124,
      "key": "A minor",
      "duration_sec": 228
    }
  ]
}
```

No `energy`, `isrc`, local path, or Lexicon library identifier in the v1 request. The backend pairing credential maps to one DJ. The destination set ID is a path parameter and is authorized with the ordinary set-owner check.

Proposed backend boundary: `POST /api/setbuilder/sets/{set_id}/imports/lexicon`. Validate with a dedicated Pydantic schema, require a valid unrevoked Lexicon-import credential, enforce a conservative batch cap, and return the same added/deduped summary contract used by existing imports. Keep the exact route and response shape consistent with the existing setbuilder import endpoints after inspecting them during implementation.

## Files and call sites

- `server/app/api/setbuilder.py` — owner-checked Lexicon import route and pairing-token dependencies, unless pairing is placed in a focused adjacent router.
- `server/app/schemas/setbuilder.py` — strict import request/response schemas.
- `server/app/services/setbuilder/pool.py` — Lexicon candidate conversion and existing add/dedupe flow; do not accept client-controlled provenance for the global track store.
- `server/app/models/user.py` and a new migration only if the current credential model cannot store a revocable per-DJ plugin token hash.
- `server/app/services/` — a small pairing/token service if existing device-pairing patterns do not fit; return the raw credential only once and store a one-way hash server-side.
- `server/tests/` — API boundary, owner-isolation, pool-additive, no-request-write, and no-energy-store regression tests.
- `lexicon-plugin/config.json` and action JS under `lexicon-plugin/` — selected-track permission, HTTPS POST allowlist, confirmation/preview, explicit version header/body, and user-readable response handling.
- `bridge-app/` packaging is deliberately excluded from this first implementation. Manual plugin ZIP installation is supported by Lexicon and can be added in a separate distribution issue after the contract stabilizes.

## Ordered TDD tasks

### 1. Confirm the existing import and auth patterns

Read the current REST pool-import routes and `#524` import implementation. Reuse its `PoolCandidate`/`import_candidates` semantics. Inspect existing DJ pairing credentials for revocation and encryption before choosing token storage. Do not add a new dependency.

### 2. Pin API invariants with failing boundary tests

Add tests proving: valid owner token imports candidates into only the requested owned set; invalid/revoked token is rejected; another DJ's set is not disclosed or changed; malformed/oversized payload is rejected; duplicate candidates are counted according to existing pool behavior; `requests` is unchanged; no Lexicon payload creates/updates global `Track.energy`; Energy and ISRC fields are rejected rather than silently trusted.

### 3. Implement the smallest secure service/API slice

Implement pairing and revocation with the existing credential conventions. Add the strict request schema and route. Call the existing additive pool import service with commit/rollback boundaries consistent with neighboring routes. Return counts only; never reflect local paths, exception text, or tokens.

### 4. Implement the Lexicon plugin

Require Lexicon's selected-track read permission only. Present the selected count and destination set before upload. Send only the fields in the accepted contract, in a single request at a time, with no credential in a URL or log. Store the paired token in Lexicon's documented private action storage with a clear notice that Lexicon does not document at-rest encryption for it; provide a disconnect action that clears it and calls server-side revocation, and show a concise result/error report.

### 5. Verify, then add packaging only as a separate slice

Run focused backend tests and repository CI checks for the backend and plugin's packaging/type checks. If plugin packaging into bridge-app is still wanted, file a separate issue with Windows/macOS/Linux path, upgrade, removal, and reinstallation behavior before modifying its installer.

## Deferred measured-energy slice

No implementation task for Phase B is ready. Resume only after the vendor exposes a documented stable identity and Energy-origin field, or after product approval of an explicit track-confirmation flow with a clear disclosure that the field may be analyzer-, Find Tags-, or manually sourced. Then design the owner-scoped resolver and ensure its rows are excluded from community consensus and the shared Track store.
