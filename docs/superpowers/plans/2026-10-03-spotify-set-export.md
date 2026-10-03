# Spotify WrzDJSet Playlist Export Plan

1. Add encrypted Spotify OAuth fields, redirect URI configuration, playlist ID storage, and the Alembic migration.
2. Add OAuth start/callback/status/disconnect routes, token refresh, state validation, and lifecycle tests.
3. Add Spotify track resolution and private playlist writing. Pin known-ID resolution, unresolved reporting, explicit skip, ordering, batching, and success-state behavior with tests.
4. Extend export schemas/routes and regenerate OpenAPI and dashboard API types.
5. Wire Spotify into the WrzDJSet export modal and cover connect, export, and success states.
6. Run targeted and full required verification, resolve review findings, and ship as a draft PR linked to issue #406.

## Remaining issue scope

Apple Music playlist writes depend on Apple Music platform integration. Broader cloud-provider search/library/import/export foundations require a separate design session. Both remain outside this Spotify PR.
