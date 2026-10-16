# Cloud Music Providers as First-Class Sources

**Status:** design for issue #741. This document defines the provider contract and migration path; it does not add provider behavior.

## Goal

Make catalog search, DJ libraries, playlist import, and playlist export available through one provider contract. A provider may implement any subset of those capabilities, and each capability must report whether it is available from public catalog credentials, a linked DJ account, or both. The contract should let Apple Music be added without another provider-specific account model or export flow.

## Current shape

Provider behavior currently spans separate services and account fields. `User` has encrypted Tidal, Beatport, and Spotify token columns; Spotify and Beatport also have transient OAuth state columns. Beatport's current login route collects the DJ's username and password, then the server logs in, follows a session-based authorization-code redirect, and exchanges the code for tokens. The existing Beatport state and verifier columns are cleared on token save, but the current login flow does not use a PKCE challenge or verifier. Search returns a shared `SearchResult`, but each result has only a Spotify ID field plus a free-form `source`. WrzDJSet stores namespaced track IDs such as `tidal:123` and `spotify:abc`.

WrzDJSet URL import currently accepts Spotify and Tidal and rejects Apple Music, SoundCloud, YouTube, and pasted Beatport URLs. Beatport playlist import does exist through a separate connected-account picker that lists the DJ's playlists and imports one by ID; the parser's Beatport message directs DJs to that flow. The URL parser validates HTTPS, host, path, and identifier, then importers call provider APIs. It deliberately does not fetch user-supplied URLs. Playlist export has a shared track collector and preflight endpoint, but separate Spotify and Tidal resolvers and writers. Spotify export chunks writes at 100 items and can remove a partial playlist; Tidal resolves and writes in its own module and currently leaves a newly created playlist if adding tracks fails. The current design therefore has useful seams, but no common provider catalog or account abstraction.

## Decision

Use a static provider registry with capability-specific adapter interfaces, a shared DJ-provider connection table, and orchestration shared only where the operation's invariants are actually common. Keep provider-specific API calls, credential handling, matching rules, pagination, and write/compensation semantics inside each adapter.

This gives the dashboard and API one discoverable capability contract without pretending every service has the same authentication or playlist-write behavior. Existing provider integrations remain usable while readers are migrated; no flag-day rewrite is required.

## Provider contract

A provider is a stable identifier plus display metadata, capabilities, account requirements, and adapters for the capabilities it implements. Registry metadata is server-owned; it is not inferred from the presence of a user's token and is never accepted from a client as authority.

The initial contract exposes these independent capabilities:

| Capability | Contract |
| --- | --- |
| `track_search` | Search the provider catalog and return normalized tracks. It declares whether search uses application credentials, a DJ connection, or either. |
| `track_resolve` | Resolve a WrzDJ track to a provider item. Resolution methods are explicit: an exact provider-native ID, exact ISRC, then title-and-artist candidate search with provider-specific confidence thresholds. |
| `library_import` | Page through the connected DJ's saved tracks or equivalent library. It is separate from playlist import because providers expose different library concepts. |
| `playlist_import` | Import a selected playlist by provider ID or validated public URL. Metadata and tracks are read through the provider API, not by fetching the submitted URL. |
| `playlist_export` | Create a new playlist and populate it with an ordered list of resolved provider item IDs. It declares visibility options, write limits, and whether it can compensate for partial writes. |

The normalized track passed between adapters contains `provider_id`, `provider_track_id`, title, artists, album, ISRC, duration, artwork URL, provider URL, and optional BPM/key/genre. Provider IDs stay namespaced in WrzDJSet storage (`provider_id:provider_track_id`); the normalized fields do not replace provider identity. Missing metadata stays missing rather than being fabricated. Existing `SearchResult` fields can be mapped during migration; the shared schema should represent provider IDs as a map rather than adding one nullable ID field per provider.

Each capability is independently configured and reports a typed availability state: `available`, `requires_account`, `not_configured`, `temporarily_unavailable`, or `unsupported`. The dashboard must distinguish “this provider cannot do this” from “this DJ has not connected an account.”

## Account connections and credentials

Replace new per-provider `User` columns with a `UserProviderConnection` record keyed uniquely by `(user_id, provider_id)`. It stores the provider account's non-secret display identity, granted scopes, connection state, credential strategy, expiry metadata, and a versioned credential payload encrypted with the existing `EncryptedText` type. The credential payload may contain an access token, refresh token, or provider-specific user token; plaintext credentials never enter API responses, logs, error details, or analytics.

The provider adapter declares credential lifecycle operations independently:

- `refresh`: refresh server-side when the provider supports it.
- `reauthorize`: mark the connection as requiring user consent when refresh is unavailable or rejected.
- `revoke`: revoke remotely when the provider offers a supported revocation endpoint.
- `disconnect`: always clear local credentials and account identity after the disconnect request; remote revocation is best effort and its outcome is recorded without retaining the secret.

Do not assume all providers issue refreshable OAuth tokens. Apple Music's web MusicKit flow manages the Music User Token in the browser, and user-library operations require that token; catalog search can use a developer token without a DJ account. The adapter must be able to request a fresh user token through MusicKit and exchange it with WrzDJ for an encrypted server-side credential. A missing or rejected Music User Token moves the connection to `reauthorize`; it is not treated as a refresh failure loop.

OAuth state and PKCE verifiers are short-lived, single-use authorization attempts bound to the authenticated DJ and browser session. They do not live in the long-lived connection row. Callback state is validated before the provider token exchange. Disconnect and reconnect invalidate outstanding attempts.

Account status responses expose provider ID, account display name when available, granted capabilities, connection state, and a safe next action. They never expose tokens, raw provider errors, or credential payloads.

## Shared resolve and export flow

Keep a shared orchestration layer around the existing `collect_export_tracks` output. For a target provider it:

1. Checks that playlist export is configured and that the DJ has the required connection.
2. Resolves every ordered track using the target adapter's declared cascade: exact namespaced provider ID, exact ISRC where supported, then title-and-artist search. Ambiguous or below-threshold candidates remain unresolved.
3. Returns a preflight result containing the source order, resolved provider IDs, unresolved entries with their original positions and reason codes, and the provider's current connection state. No playlist is created during preflight.
4. Requires an explicit DJ choice to skip unresolved items. The default is to block export while any track is unresolved; the client cannot imply consent by omitting an option.
5. Creates a fresh playlist and writes only the chosen resolved items in source order. The adapter owns provider limits, batch boundaries, and any required delay or pagination.
6. Marks the set exported and records the provider playlist ID only after all writes succeed. On a write failure, the adapter runs its declared compensation when supported and returns an error that identifies whether cleanup succeeded. The set is not marked exported on either failure path.

The common invariant is no silent omission, stable ordering, and no success state before all provider writes complete. “Batch” is an adapter operation: Spotify currently accepts at most 100 playlist items per write, while other providers may accept a single complete track list or replace playlist contents on update. The orchestrator must not impose one provider's batch size or cleanup operation on another. If an adapter cannot safely create a new ordered playlist or report partial-write state, it cannot advertise `playlist_export`.

Track matching remains provider-specific. Shared code may provide title/artist normalization and version filtering, but thresholds and query construction belong to the adapter because catalog behavior differs. A provider-native ID is trusted only when the namespace matches the export target and the identifier passes that adapter's validation.

## Import and search behavior

Search and import use the same normalized track shape and provider registry. A search result preserves the source provider ID and URL so adding it to the set pool retains its original identity. Existing ISRC/title-and-artist deduplication remains the pool's responsibility.

Playlist URL handling keeps the current SSRF boundary: accept only HTTPS URLs from exact provider host allowlists, validate path and ID shape, and parse into `{provider_id, playlist_id}`. Never issue an HTTP request to the submitted host or URL. The provider adapter fetches by validated identifier from its configured official API host. A short link is supported only when the provider API can resolve it without following an arbitrary user-controlled redirect. Public playlist import does not require the DJ to connect an account unless that provider requires authentication for the requested playlist.

Library import is a separate dashboard action from public playlist URL import. It requires an account connection and uses opaque pagination cursors internally; the UI only receives normalized page results. Import is read-only and never follows, likes, or edits items in the DJ's library.

## Dashboard and API surfaces

The API exposes a provider catalog for authenticated DJs, including capability availability and any safe account action. A separate connection endpoint starts linking, returns the provider's authorization handoff, reports status, and disconnects. Search, library import, playlist URL preview/import, and set export call the capability interfaces rather than branching on provider names in route handlers.

The existing event **Cloud Providers** card becomes capability-driven. It lists supported providers, what they can do, whether the DJ is connected, and a link/reauthorize/disconnect action. It does not imply that a provider supports every feature.

The set-builder import modal gains provider library choices only when `library_import` is available, and playlist URL preview uses the parsed provider capability to explain support before import. The export modal lists only configured `playlist_export` providers; it uses the common preflight response and presents unresolved tracks with an explicit skip action. File exports remain separate targets because they do not use a cloud-provider account.

Generated API types should be derived from the provider catalog and capability response. Avoid hard-coded provider lists in the dashboard except for provider display assets; API capability data drives action availability.

## Provider rollout and access requirements

Recheck each provider's current developer terms, app status, and limits immediately before implementation. Vendor access and endpoint policies change independently from WrzDJ releases.

| Provider | First-wave capability plan | Access and implementation gate |
| --- | --- | --- |
| Spotify | Migrate current catalog search and set export; retain current behavior where enabled. Add playlist import and library import only if the app's current access mode exposes the required endpoints. | Development Mode currently requires the app owner to have Spotify Premium and allows up to five authorized users; broader use requires Extended Quota approval. Spotify's published Extended Quota criteria currently require an established organization, a launched service, and at least 250,000 MAU. Endpoint access and policy changes are subject to Spotify's migration guidance. Treat production multi-DJ rollout as blocked until the app's actual quota mode and endpoint grants are verified. |
| Tidal | Migrate the current per-DJ link, search, collection sync, and set export behind the contract without expanding its API surface. | WrzDJ currently uses the `tidalapi` client and existing Tidal account flow. No public, stable Tidal developer-program requirements were found in the official materials reviewed for this design. Preserve the working integration, but verify authorization and terms with Tidal before adding new library or playlist capabilities. |
| Beatport | Migrate the current account, search, metadata, and connected-account playlist-import behavior. Do not claim pasted public-URL import or playlist export. | The current route collects the DJ's username and password, the server creates a Beatport session, obtains an authorization code through a redirect, and exchanges it for tokens. The current flow does not use PKCE, although legacy state/verifier columns exist and are cleared after token save. This research did not find a public official API access and quota policy that establishes general third-party availability. Before migrating account linking, confirm the allowed auth pattern with Beatport; do not expand or duplicate password collection, and use a provider-supported authorization redirect/PKCE flow if available. |
| Apple Music | First new provider after the registry and connection foundation: catalog search, playlist URL import, library import, and playlist export, subject to MusicKit consent and subscription availability. | Requires Apple Music API developer-token signing credentials (Media ID and private key) and user consent for personalized data. Catalog search uses a developer token; library reads and playlist creation require a Music User Token. The web MusicKit flow manages that token, so user authorization must be exercised in the dashboard. |
| SoundCloud | Second new provider, after app credentials and terms are confirmed: track search, playlist URL import, library/likes import, and playlist creation/update. | SoundCloud currently requires an Artist Pro subscription to register API apps. Its API uses OAuth 2.1 with PKCE for user resources; client credentials cover public resources. Its documented playlist API creates playlists with tracks and updates the playlist's `tracks` property, so test ordering and replacement behavior before enabling export. |
| YouTube / YouTube Music | Not in the first wave. Keep the URL recognized and return an explicit unsupported capability state. | The existing URL parser recognizes YouTube, but this design has not established a supported YouTube Music catalog, library, or playlist contract for WrzDJ. Reconsider only after a separate official API and terms review. |

The first implementation sequence is: (1) provider registry and safe catalog/account status contract; (2) additive connection storage and compatibility reads for current Spotify/Tidal/Beatport records; (3) migrate Spotify and Tidal search/export flows without changing behavior; (4) migrate Beatport's existing uses; (5) Apple Music adapter; (6) SoundCloud adapter after the stated access gate. This ordering keeps existing DJ workflows working while the new providers are added.

## Migration path

Use an expand-and-contract migration. First add the connection table and adapters while existing columns remain the source of truth. The token columns use `EncryptedText`, which decrypts each value when SQLAlchemy reads it and encrypts the new value when it is written. Therefore the backfill must run as application code through the ORM: it reads the legacy token values, serializes a versioned credential payload in memory, and assigns that plaintext JSON to the new `EncryptedText` field. It must never copy raw Fernet ciphertext into the payload or use a SQL-only ciphertext copy.

Make the backfill resumable and safe around token refresh. Before its first batch, deploy one compatibility accessor and route every provider credential read, refresh, reconnect, and disconnect through it. Each operation takes a lock on the owning `User` row and uses one database transaction. An existing connection row is authoritative even when it is marked disconnected: reads never fall back to legacy fields; refresh updates that row; reconnect writes the new row. Disconnect clears the connection's credentials and all corresponding legacy token fields atomically, and leaves or creates a disconnected row as a tombstone. Remote revocation remains best effort, but local disconnect state must commit as one unit. With no connection row, the accessor may read and refresh legacy credentials while holding the same lock.

After this compatibility release is active, process users in keyset batches. For each user, lock that row, load legacy values through `EncryptedText`, create only missing provider connections, and commit all of that user's connection rows in one transaction. Enforce the `(user_id, provider_id)` unique key and skip every existing row, including disconnected tombstones, so retries cannot overwrite a newer authorization or restore credentials the DJ intentionally disconnected. If decryption or serialization fails, roll back that user's transaction, leave legacy columns untouched, and stop or report a redacted failure. Logs and progress output may contain only aggregate counts and non-secret provider/user identifiers; they must never contain tokens or serialized credential payloads. A rerun continues with missing connections. Do not dual-write new secrets indefinitely.

Migrate service call sites provider by provider: authentication and status endpoints, search, event sync, enrichment, recommendation, agent tools, set-builder imports, and exports. Remove the legacy columns only after all reads and writes have moved, a production rollout confirms the new record is populated, and an explicit follow-up migration is reviewed. OAuth state and PKCE verifier columns are not copied as active authorization attempts; outstanding flows must restart after deployment. Beatport's current username/password and server-side redirect flow must be represented accurately during compatibility migration; replacing it with PKCE is separate future work that depends on confirming Beatport supports and permits that flow.

Keep provider-specific set destination IDs (such as `Set.tidal_playlist_id` and `Set.spotify_playlist_id`) during this issue's migration. They describe provider outputs attached to a set and are a separate concern from a DJ's provider account connection. A later schema change may replace them with a provider export record if multiple exports per set become a product requirement.

## Invariants

- A provider can advertise only capabilities implemented by its registered adapter and enabled by server configuration.
- No secret appears in an API response, log, error detail, or unencrypted database column.
- After compatibility routing is deployed, an existing provider connection row is authoritative; a disconnected row prevents legacy fallback, and refresh, reconnect, disconnect, and backfill serialize on the owning `User` row.
- Account link state is bound to a DJ and browser attempt; replayed, expired, or mismatched state cannot connect an account.
- A URL import never fetches a caller-controlled host or follows an arbitrary redirect.
- Every input track remains represented in export preflight, including orphans and ambiguous matches.
- Export never silently drops unresolved tracks, preserves the selected track order, and marks success only after every provider write succeeds.
- A provider adapter reports whether failed partial writes were cleaned up; failure never marks the set exported.
- Existing provider behavior remains available until its call sites have migrated and the legacy storage is safe to remove.

## Sources checked on 2026-10-14

- [Apple MusicKit overview](https://developer.apple.com/musickit/) — catalog, user authorization, and playlist support.
- [Apple Music user authentication](https://developer.apple.com/documentation/applemusicapi/user-authentication-for-musickit) — developer token versus user token and MusicKit Web token management.
- [Apple Music create a library playlist](https://developer.apple.com/documentation/applemusicapi/create-a-new-library-playlist) — playlist creation requires a Music User Token.
- [Spotify February 2026 Web API migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide) — development-mode restrictions and endpoint changes.
- [Spotify quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes) — development and extended quota access requirements.
- [Spotify February 2026 access update](https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security) — later postponement of existing-integration endpoint changes.
- [SoundCloud API registration](https://developers.soundcloud.com/docs/api/register-app) — Artist Pro requirement for app credentials.
- [SoundCloud API guide](https://developers.soundcloud.com/docs/api/guide) — OAuth 2.1/PKCE, search, playlist import, and playlist writes.
- [SoundCloud API rate limits](https://developers.soundcloud.com/docs/api/rate-limits.html) — published request limits.

The Tidal and Beatport access statements above are bounded findings from the official-source search performed for this design, not claims that private or partner documentation does not exist. Implementation work must confirm current access directly with those providers.
