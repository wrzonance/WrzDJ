# Issue #526 — LexiconDJ integration research and decision

**Date:** 2026-10-03  
**Issue:** #526 (`research(setbuilder): LexiconDJ as an optional measured-energy source of truth for WrzDJSet (+ library sync)`)  
**Status:** Research complete; pool-import implementation is a follow-up. Automatic measured-energy matching is blocked on supported identity and provenance fields from Lexicon.

## 1. Decision summary

Keep Lexicon integration inside WrzDJSet. The request-queue enrichment pipeline must not call Lexicon or depend on a user's local app.

The current WrzDJ code already has two distinct energy paths:

- `Track.energy` is the shared master-track-store field. Soundcharts can write measured audio features when its setting is enabled; `lexicon` is already reserved at precedence 90 in `services/tracks/provenance.py`.
- `TrackVibe.energy` is the global LLM cache, while `TrackVibeOverride` and community votes feed WrzDJSet's read-time own → community → LLM resolver. `SetPoolTrack.energy` is a separate, currently non-authoritative pool value used as a fallback by pass 1.

The requested seamless match-and-enrich path is **not ready to implement safely**. Lexicon's current documented Track schema exposes integer Energy from 0 through 10, but does not document an ISRC field. Its Energy column also does not disclose whether its value came from audio analysis, Find Tags, or a manual edit. The plugin can read the same documented fields as the Local API, so moving the integration into a plugin does not solve either gap.

Proceed with a separate, narrow `import_from_lexicon` follow-up for explicitly selected library tracks into the DJ's own set pool. Do not call those values verified measurements, do not infer ISRC, and do not write imported Lexicon values into the shared `Track.energy` store. The first version should omit Energy from import. Revisit energy enrichment only after Lexicon provides documented stable identity and value-origin fields, or after a separately designed user-confirmed matching flow can prove the target track and explain that Lexicon does not expose analysis provenance.

## 2. Scope and boundaries

**In scope**

- Research the current WrzDJ energy, import, identity, and authorization paths.
- Compare the documented Lexicon Local API and plugin surfaces, plan gates, energy scale, and analysis constraints.
- Decide whether a plugin-driven library import and measured-energy enrichment can proceed safely.
- Define the smallest follow-up implementation slice and its security invariants.

**Out of scope**

- Any runtime or schema changes in this research PR.
- Lexicon calls from normal WrzDJ guest request enrichment.
- Local API polling from the bridge. The API is unauthenticated and listens on all interfaces.
- Automatic use of Lexicon Energy as an analysis-provenance-confirmed measurement.
- Cue-point sync, Lexicon BPM/key overrides, SonoVault, Lexicon CSV editing, or bundling an installer in bridge-app.

## 3. Verified current state in WrzDJ

The `tracks` store is shared across users and has per-field provenance. Its energy precedence already reserves `lexicon: 90`, above Soundcharts and the existing cloud metadata providers at 50, and above LLM at 10 (`server/app/services/tracks/provenance.py`). Request-time enrichment writes Soundcharts audio features only when `soundcharts_audio_features_enabled` is enabled and an ISRC is available (`server/app/services/sync/enrichment_pipeline.py`). That integration is shared-track enrichment and is not a safe place for an owner's private Lexicon import.

WrzDJSet's vibe resolution is a separate system. It resolves the viewing DJ's explicit override, then community consensus, then the global LLM cache (`server/app/services/setbuilder/vibe_resolver.py`). Community consensus currently considers all override rows with values, so a new non-vote source must be explicitly excluded from community aggregation before it can be added. Pass 1 uses the resolved vibe energy when present and falls back to `SetPoolTrack.energy`; the pool column and the vibe cache are not interchangeable (`server/app/services/setbuilder/pass1_deterministic.py`).

Existing pool import code accepts `PoolCandidate.energy`, writes it to a pool row, and may also write carried fields into the shared master track store (`server/app/services/setbuilder/pool.py`). Its provenance is derived from server-trusted Beatport/Tidal IDs; other client-supplied identities are marked `legacy`. A Lexicon plugin must not be allowed to claim the global `lexicon` source merely by posting an energy value. Any future Lexicon energy path must be owner-scoped, carry server-verified source provenance, and stay out of community votes unless the DJ explicitly votes on it.

## 4. Lexicon evidence and answers to the issue's questions

Research is based on Lexicon's official [Local API documentation](https://www.lexicondj.com/docs/developers/api), [plugin documentation](https://www.lexicondj.com/docs/developers/plugin), [analyzer manual](https://www.lexicondj.com/manual/analyzer), and [pricing feature list](https://www.lexicondj.com/pricing), accessed 2026-10-03. The API schema at `https://www.lexicondj.com/developer/api-docs.yaml` was inspected directly; no `isrc` field appears in its Track schema.

### 4.1 Energy scale

The documented Track schema defines `energy` as an integer with minimum 0 and maximum 10. Lexicon says its audio analyzer uses an absolute-based system and fills the Energy field. **No normalization is needed:** when a user elects to transfer the Energy field, the numeric mapping is identity, with WrzDJ validation still enforcing integer 0–10.

This does not establish that any given value was produced by audio analysis. Lexicon also offers Find Tags, which fills the same Energy field with a different algorithm, and the API schema does not identify the method or whether the value was edited. For that reason, an imported value cannot currently be described as a confirmed measured result.

### 4.2 Track identity / ISRC

The documented API supports paginated track reads and exposes a Track schema, but that schema contains no ISRC field. The plugin docs state that plugins can read the same Local API fields. The issue's proposed ISRC match-and-enrich path therefore has no documented input key today. Do not rely on undocumented fields, database inspection, or reverse engineering. Title/artist matching is not strong enough to silently override energy for remasters, edits, versions, or similarly named recordings.

### 4.3 Plan requirement

The current pricing feature matrix marks Local API, Plugin Support, and Analyze BPM / Beatgrid / Key / Energy as unavailable on Free and available on both Essential and Ultimate. The integration therefore requires a paid Lexicon tier. The official material does not distinguish these capabilities between Essential and Ultimate.

### 4.4 Local API risk and plugin suitability

The Local API is disabled by default, has no authentication, and listens on every network interface. It exposes mutating endpoints as well as reads. This makes bridge polling a poor default, especially on venue or shared Wi-Fi. The documented plugin model supports per-action track read permissions and outbound GET/POST domain allowlists. A plugin posting directly to a fixed WrzDJ HTTPS API is topology-agnostic and avoids opening Lexicon's local API to other devices. It remains an opt-in, paid-client integration.

Lexicon documents plugin ZIP installation under `Documents/Lexicon/Plugins`, selected/all track reading, paged all-track iteration, playlist reads, playlist creation, and outbound network requests. The initial implementation should be explicitly run by the DJ and read only selected tracks; do not scan the full library by default. The bridge-app installer is not needed for an initial user-installed ZIP and should be evaluated separately after the plugin contract is stable.

### 4.5 Licensing / data handling

The Terms page currently displays a version dated 2026-09-23 that takes effect 2026-10-23, and says the previous Terms remain in force until then. The previous version was not independently obtained for this research, so the exact current license posture remains unverified. The displayed upcoming version does not itself grant WrzDJ a license to redistribute Lexicon or library data. Keep the integration user-initiated: the DJ runs their own Lexicon, selects tracks, and sends only fields necessary for their own WrzDJSet pool. Never bundle Lexicon software or transmit the full library automatically. Recheck the Terms in force before shipping.

## 5. Chosen architecture for the follow-up

### Phase A — selected-track pool import

Add `import_from_lexicon` as a separate #442-family import source. The user selects one or more Lexicon tracks in the plugin, selects a destination WrzDJSet, reviews the import, and submits a bounded batch to a DJ-scoped WrzDJ endpoint over HTTPS. Import only title, artist, and other explicitly approved display/import fields; omit Energy and ISRC. Lexicon's local track ID is only an ephemeral request reference and must not be treated as globally unique.

The endpoint resolves its owner from a narrow, revocable credential paired to that DJ; it must not accept a client-supplied owner ID. Store only a one-way token hash server-side. The plugin may retain the bearer in Lexicon's documented private action storage; do not claim Lexicon encrypts that storage, and explain that local users with access to the Lexicon profile can access it. It validates all fields and batch size, checks set ownership, creates pool membership additively through existing pool services, and never writes `requests`. Existing source dedupe and undo behavior should be preserved. If the import surface is an agent mutation, it belongs in the closed allowlist, requires `rationale`, and gets a regression test that proves `requests` remain untouched, matching #524.

Avoid accepting an arbitrary API base URL while attaching a bearer token. The packaged production plugin should whitelist the WrzDJ HTTPS host. Self-hosted/custom origins need a separate, reviewed pairing/configuration flow.

### Phase B — owner-scoped Lexicon Energy (blocked)

Do not implement until both identity and origin are solved. Lexicon must document a stable per-recording identifier usable by WrzDJ (prefer ISRC) and a way to distinguish analyzer output from Find Tags/manual values, or WrzDJ must design an explicit per-track user-confirmed mapping with clear limitations. Then store the value only in a per-DJ WrzDJSet energy layer; never let a plugin-authenticated payload write the global `Track.energy` field at Lexicon precedence. Resolution order should be explicit DJ edit → that DJ's accepted Lexicon value → community → LLM, with Lexicon observations excluded from community vote aggregation. Removal/revocation must reveal the next lower tier without changing another DJ's data.

If Lexicon later exposes a documented value and identity contract, the existing `lexicon: 90` master-store tier can be reconsidered only if the value is proven suitable for global sharing. The current reservation alone is not authorization to write owner-provided values to the shared store.

## 6. Follow-up acceptance criteria

For Phase A:

- Plugin action reads selected tracks only and presents a preview before upload.
- Narrow pairing credential is DJ-scoped, revocable, stored as a one-way hash server-side, and accepted only by the Lexicon import route.
- Endpoint rejects unknown fields, out-of-range values, oversized batches, invalid or expired credentials, and non-owned set IDs with safe errors.
- Imported tracks are additive, deduplicated through established pool rules, and undoable where routed through the agent mutation flow.
- The import does not write `requests`, does not write shared `Track.energy`, does not claim ISRC, and has no effect on another DJ's pool or vibe.
- Plugin works through outbound HTTPS without Lexicon Local API being enabled.
- Contract versioning is explicit between plugin and backend; older/newer plugin versions fail with a user-readable compatibility message.

Phase B is not accepted until Lexicon's documented fields meet §5 Phase B prerequisites and the owner-scoped resolver has tests for precedence, isolation, removal, and community exclusion.

## 7. Open external dependency

Ask Lexicon to document whether the Local API/plugin Track object can expose ISRC, and whether it can identify values produced by the audio analyzer separately from Find Tags and manual edits. Until that is answered in public documentation, automated existing-track enrichment remains blocked.

## 8. Self-review

- The issue's premise that SetPoolTrack/TrackVibe energy is a single LLM field is corrected: these are separate systems, and the shared Track energy store is separate again.
- The issue's Local API description is corrected: current documentation says all interfaces and read/write endpoints, not localhost-only/read-only.
- The numeric schema and analyzer semantics are kept distinct: 0–10 identity mapping is known; per-value analyzer provenance is not.
- The plugin is not treated as a way to recover undocumented API fields.
- No claims depend on the Terms version that takes effect after the research date.

🤖 Co-authored by Codex gpt-6-luna.
