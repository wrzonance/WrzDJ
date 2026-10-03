# Implementation plan — selected Lexicon tracks into a WrzDJSet pool

**Parent research:** `docs/superpowers/specs/2026-10-03-issue-526-lexicondj-design.md`  
**Related roadmap:** #442 Family 4  
**Scope:** Phase A only. Do not implement measured-energy matching while Lexicon's documented Track schema lacks ISRC and analyzer-origin fields.

## Goal and invariants

Let a DJ explicitly select Lexicon tracks and add them to one of their own WrzDJSet pools through the Lexicon plugin. Every imported row belongs to the destination set; the plugin cannot select another owner, create a guest request, or write metadata into the shared track store.

1. A credential is issued to a DJ only from their authenticated WrzDJ account session. The server stores only its hash; it expires after 90 days and is revocable from WrzDJ account settings.
2. The import endpoint derives the actor from that credential, and independently checks that the destination set belongs to the actor. Request JSON never supplies an owner ID.
3. The v1 payload contains only validated title and artist. It omits Lexicon local IDs, ISRC, Energy, and other metadata.
4. Import is additive and atomic. It does not write `requests` or any field in the shared `Track` store.
5. Production plugin traffic goes only to a build-time fixed, allowlisted WrzDJ HTTPS origin. No runtime API-base URL is accepted alongside a bearer.
6. Requests are idempotent for seven days by credential + request UUID + canonical body hash. Reuse of the same UUID with a different body is rejected.
7. Lexicon title/artist signature dedupe can conflate different versions with identical names. The plugin must show this limitation before confirmation and identify skipped duplicates in its result.
8. Check the Terms in force and record that user-initiated plugin transfer is permitted before enabling the feature. Hold if unclear or prohibited.

## Data shapes and interfaces

Contract version is sent in `X-WrzDJ-Lexicon-Contract-Version: 1`. Check that header before parsing the strict body schema so old/new contracts get a readable compatibility error.

```json
{
  "tracks": [
    { "title": "Track title", "artist": "Artist name" }
  ]
}
```

Use a 200-track maximum and reject larger requests atomically; the plugin does not chunk or retry with a new UUID. It creates and persists a random request UUID with the pending payload before the POST, reuses both on a transport retry, and replaces the pending request only after receiving a successful response. A pending request older than seven days requires a fresh preview and UUID because its server receipt may have expired. The set ID is in the URL path and must pass the ordinary set-owner check. No arbitrary remote origin is accepted.

Proposed boundaries (confirm route naming against existing setbuilder imports during implementation):

- `POST /api/setbuilder/sets/{set_id}/imports/lexicon` — narrow Lexicon credential; import title/artist tracks.
- `POST /api/setbuilder/lexicon/credential/revoke` — same credential may revoke itself.
- Authenticated WrzDJ account settings — issue, list status/expiry, replace, and revoke the DJ's credential without the plugin.

Create one credential per DJ. Re-pairing revokes the prior credential before returning the new opaque token exactly once. Persist token hash, owner, scope, created/expiry/revoked timestamps. The plugin stores the token in Lexicon private action storage; document that Lexicon does not document at-rest encryption for this store. For disconnect, call server revocation first and erase local storage only after success; if offline/failing, retain the token and offer retry. WrzDJ account settings remain the recovery/revocation path if the plugin is removed or loses its token.

Store a seven-day idempotency receipt keyed by credential and request UUID, containing canonical body hash and response summary. Same key/hash replays the saved summary; same key/different hash returns 409. Expired receipts are removed opportunistically on import and by any existing periodic cleanup mechanism; do not store the submitted track names in the receipt.

## Files and call sites

- `server/app/api/setbuilder.py` — owner-checked Lexicon import route and narrow-token dependency, unless a focused adjacent router fits better.
- `server/app/schemas/setbuilder.py` — strict contract schema (title/artist only) and response schema.
- `server/app/services/setbuilder/pool.py` — Lexicon candidate conversion and existing additive import flow. Confirm that title/artist-only candidates cannot write any shared `Track` values.
- `server/app/models/user.py` and a new migration only if the existing credential model cannot hold a revocable per-DJ token hash.
- New focused pairing and idempotency models/migration only if no existing credential and idempotency patterns fit; never add raw bearer fields.
- `server/app/services/` — pairing, revoke, token verification, body hashing, and idempotency service, following current auth/rate-limit conventions.
- WrzDJ account settings API/UI — create/replace/revoke credential and display status/expiry; never redisplay raw token.
- `server/tests/` — pairing, auth, ownership, atomicity, idempotency, no-request-write, and no-shared-store-write regression tests.
- `lexicon-plugin/config.json` and action JS under `lexicon-plugin/` — selected-track-only permission, fixed production HTTPS host allowlist, preview/duplicate disclosure, one request UUID per pending payload, and compatibility/error handling.
- `bridge-app/` packaging is excluded. Manual plugin ZIP install is supported by Lexicon; installer work needs a separate issue after the contract stabilizes.

## Ordered TDD tasks

### 0. Verify legal and product prerequisites

Before implementation, inspect the Terms that are then in force and record the specific evidence that permits the user-initiated plugin transfer to WrzDJ. The currently visible Terms page states a future effective date; it is not sufficient evidence. If current terms are unavailable, unclear, or prohibit this use, stop before implementing the data-transfer feature and ask the operator to resolve the vendor/license question. Do not contact the vendor without authorization.

### 1. Confirm current import and auth patterns

Read the REST pool-import routes and #524 implementation. Inspect current account credential and token-revocation patterns, rate limiting, and transactional pool import. Confirm title/artist-only imports do not call `upsert_track` with values; add an explicit guard if necessary. No client-supplied provenance is trusted.

### 2. Pin API invariants with failing boundary tests

Test authenticated credential issuance, one-time token disclosure, token hashing, one active token per DJ, 90-day expiry, server-side revocation, and recovery through account settings. Test contract-version header mismatch before body validation, unknown fields (including `energy`, `isrc`, `genre`, `bpm`, `key`, `duration_sec`) rejected, 200-row acceptance, 201-row atomic rejection, invalid/revoked/expired token rejection, another DJ's set unchanged, and all shared `Track`/`requests` rows untouched.

Test that same credential + request UUID + body returns the same result without adding rows; same UUID with a changed body returns 409; expired idempotency receipts are removed; title/artist collisions are included in the preview/result and the import confirmation text warns that versions with identical names may dedupe.

### 3. Implement pairing, strict API, atomic pool import, and idempotency

Issue a random opaque credential only from an authenticated WrzDJ account session, hash it server-side, expire at 90 days, and revoke prior credentials on replacement. Add narrow middleware/route scopes and rate limits. The self-revoke route verifies the presented token but accepts no other action. Parse the version header before schema validation. Reject over-cap payloads without partial writes. Check ownership, use the existing additive import service, and save the receipt in the same transaction as the pool changes. Never store request track names in the idempotency record.

### 4. Implement the account controls and Lexicon plugin

The account UI can issue/replace/revoke credentials and display active/revoked state and expiry; show the raw token only once. The plugin prompts for the token and destination set ID, reads selected tracks only, displays title/artist and the identity/dedupe limitation, and requires confirmation. It uses the baked-in API origin, sends the version header and request UUID, and stores pending UUID+body before sending. On a timeout it offers retry with the same payload/UUID. On disconnect it revokes remotely before clearing local storage; retain local credentials after failures. Report a failed revoke clearly.

### 5. Verify and split installer work

Run focused backend tests, account UI lint/typechecks, and plugin packaging/type checks, then canonical repo CI checks. If bridge-app should bundle the ZIP, file a separate issue covering Windows/macOS paths, upgrade, removal, and reinstallation before changing its installer.

## Deferred measured-energy slice

No implementation task for Phase B is ready. Resume only after Lexicon provides a documented stable identity and Energy-origin field, or product approves a per-track user-confirmed mapping flow with a clear disclosure that the Energy field may be analyzer-, Find Tags-, or manually sourced. Then design the owner-scoped resolver, ensure it never writes the shared Track store, and exclude its values from community consensus unless explicitly voted on.
