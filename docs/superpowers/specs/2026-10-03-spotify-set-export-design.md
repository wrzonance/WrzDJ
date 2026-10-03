# Spotify WrzDJSet Playlist Export

## Goal

Let a DJ export the ordered WrzDJSet timeline or pool to a new private Spotify playlist. Every track must resolve before playlist creation unless the DJ explicitly chooses to skip unresolved tracks. This is the Spotify slice of issue #406; Apple Music and platform-wide provider groundwork remain separate follow-up work.

## Design

- Link the DJ's Spotify account with Authorization Code OAuth. Persist access and refresh tokens plus one-time state in `EncryptedText` columns. The callback validates a short-lived, user-bound random state and an HttpOnly browser cookie before exchanging the authorization code.
- Resolve namespaced `spotify:<id>` references directly, then try an exact ISRC search, then title/artist search with the existing fuzzy matcher and unwanted-version filter. Preserve input order and report every unresolved entry.
- Add `spotify` to the existing export preflight contract. When tracks are unresolved, return the same 409 interrupt used by Tidal. Only `skip_unresolved=true` allows playlist creation with matched items alone.
- Create a fresh private playlist, then append Spotify URIs in ordered batches of at most 100. If a batch fails, best-effort remove the partial playlist from the user's library. Mark the set exported only after all batches succeed and persist its Spotify playlist ID.
- Request Spotify's private-playlist write and library-modify scopes so failed partial exports can be removed from the user's library.
- Extend the existing export modal with OAuth linking, preflight feedback, explicit unresolved-track choice, and a result link.

## Boundaries and invariants

- All Spotify user tokens and OAuth state are encrypted at rest.
- OAuth callbacks without a matching, unexpired state cannot link an account.
- No unresolved track is omitted unless the DJ confirms the skip.
- Playlist writes preserve the order of the resolved set entries and do not exceed Spotify's 100-item request limit.
- API errors do not mark the set exported.

## External API references

- [Spotify Authorization Code flow](https://developer.spotify.com/documentation/web-api/tutorials/code-flow)
- [Spotify Create Playlist](https://developer.spotify.com/documentation/web-api/reference/create-playlist)
- [Spotify Add Items to Playlist](https://developer.spotify.com/documentation/web-api/reference/add-items-to-playlist)
- [Spotify Remove Items from Library](https://developer.spotify.com/documentation/web-api/reference/remove-library-items)
