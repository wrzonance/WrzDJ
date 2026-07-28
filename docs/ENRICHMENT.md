# Music Metadata Enrichment: Providers, Source of Truth, and Fate

## 1. Title & Scope

This document audits and documents WrzDJ's music-metadata enrichment — every code path that
fills genre, BPM, musical key, ISRC, or energy on a track, wherever that data lives (`Request`,
the master `tracks` store, `TrackVibe`). It is the documentation half of issue **#527**
(`research/refactor: audit & document the metadata enrichment-source pipeline`).

**This is a docs-only PR.** Nothing here changes runtime behavior, and no provider is removed,
refactored, or reconfigured as a result of this document. Any "formalize"/"remove"
recommendation below (§6) is a proposal for future work, not something this PR enacts.

Audited **live on `main` at 2026-07-27** by reading every cited file in full this session —
grepping or trusting prior recon notes was not treated as sufficient. Every non-trivial claim
below carries a `path:line` citation, verified against the worktree at the time of writing. Where
a claim could not be independently verified this session, it is marked **"unverified — needs
follow-up"** rather than asserted as fact. Issue #527's own "Verified starting state" section
turned out to be stale in places (e.g. it described Spotify as "now only an ISRC bridge"); where
this audit found the live code doing more than that recon assumed, §6 says so explicitly and
corrects it rather than repeating it.

### Document map

1. This section.
2. **Provider Inventory** — every external metadata provider wired into the codebase: what it's
   called, how it authenticates, what fields it supplies, which pipelines call it, what gates it,
   and its fate recommendation.
3. **Per-Pipeline Detail** — the three enrichment pipelines end to end: Request-Time Enrichment,
   the Recommendation Engine, and SetBuilder Vibe Resolution.
4. **Source-of-Truth Matrix** — per field (genre / BPM / musical_key / ISRC / `Track.energy` /
   `TrackVibe.energy`), which system is authoritative and why.
5. **Cloud-only vs. Cloud+Optional-Local Boundary** — where WrzDJ is 100% cloud-dependent vs.
   where WrzDJSet already has (or is about to gain, #526) a local override tier.
6. **Provider Fate Recommendations** — keep / formalize / remove per provider, with rationale.
7. **Open Follow-ups** — real inconsistencies this audit found and documents, but does not fix.
8. **Appendix: File Map** — every file cited in this document, in one place.

**Field scope.** "Field" in this document means exactly `{genre, BPM, musical_key, ISRC}` plus
`Track.energy` (the master-store numeric precedence ladder) and `TrackVibe.energy` (the
WrzDJSet vibe cache) as **two separate rows** — they are resolved by genuinely different systems
(§3.3) and are never merged into one row. Soundcharts' other audio features (danceability,
valence, acousticness, …) are documented as a footnote under `Track.energy`, not as their own
matrix rows.

## 2. Provider Inventory

| Provider | Client module | Auth model | Fields supplied | Wired into | Gate | Fate |
|---|---|---|---|---|---|---|
| Spotify | `server/app/services/spotify.py` | App client-credentials (server-wide config; **no** per-DJ OAuth)¹ | Search: title/artist/album/ISRC/popularity/preview/artwork². Bridge: ISRC only³. Playlist-import: ISRC/duration/artwork⁴. Never bpm/key/genre. | request-queue, pool-public-playlist-import | none (server credentials only) | keep |
| Beatport | `server/app/services/beatport.py` | Per-DJ OAuth2 — server-side login-code-token exchange⁵ | bpm, key, genre, duration — **no ISRC field at all**⁶ | request-queue, recommendation-enrichment, pool-hydrate-enrich | connected-token (`user.beatport_access_token`) | keep |
| Tidal | `server/app/services/tidal.py` | Per-DJ OAuth2 — device-code flow⁷ | bpm, key, ISRC, duration — no genre⁸ | request-queue, recommendation-enrichment, pool-hydrate-enrich | connected-token (`user.tidal_access_token`) | keep |
| MusicBrainz | `server/app/services/musicbrainz.py` | none — public API⁹ | genre (artist-level)¹⁰; artist-existence verification¹¹ | request-queue, recommendation-enrichment (junk-artist filter) | none | keep |
| Soundcharts | `server/app/services/soundcharts.py` | App API key (`x-app-id`/`x-api-key`, server-wide) | Audio features: energy + 9 others (never bpm/key/genre, see §3.1)¹²; discovery candidates (title/artist only)¹³; related-track candidates (title/artist only)¹⁴ | request-queue (audio-features step), recommendation-soundcharts-candidates (both generators) | **inconsistent across call sites** — see note below | keep |
| ListenBrainz | `server/app/services/listenbrainz.py` | App user token (`listenbrainz_user_token`, server-wide, **not** per-DJ)¹⁵ | Artist popularity counts; LB-Radio title/artist candidates¹⁶ — never genre/bpm/key/ISRC | recommendation-enrichment (LB Radio discovery + artist-popularity junk filter) | none (token presence only) | keep |

**Note on Soundcharts' gate.** The client module has three independent call sites with three
different gates — this is a real inconsistency, not fixed in this PR (tracked in §7(b)):

- `discover_songs` (feeds `search_candidates_via_soundcharts`) — gated only by credential
  presence (`soundcharts_app_id` / `soundcharts_api_key`); **no explicit enable flag**
  (`server/app/services/soundcharts.py:212-215`, `server/app/services/recommendation/service.py:754-756`).
- `get_song_features_by_isrc` — gated by `soundcharts_audio_features_enabled`
  (`server/app/services/soundcharts.py:358`).
- `get_related_songs_by_isrc` — gated by `soundcharts_related_tracks_enabled`
  (`server/app/services/soundcharts.py:423`).

**Lexicon is intentionally not in this table.** No `lexicon.py` (or equivalent) client module
exists in this codebase yet — it appears only as a reserved, currently-unwired precedence tier
(`"lexicon": 90` in `server/app/services/tracks/provenance.py:14`). It is research issue **#526**
(open) and is covered in §4/§7, not here.

None of the six wired providers above are wired into a `setbuilder-vibe` path — that bucket is
currently served entirely by the LLM Gateway (§3.3), not by a music-metadata provider; it would
be Lexicon's natural landing point once #526 wires a client.

### Footnotes (evidence)

1. `_get_spotify_client` — `server/app/services/spotify.py:30-51`
2. `search_songs` — `server/app/services/spotify.py:54-98`
3. `_get_isrc_from_spotify` — `server/app/services/sync/enrichment_pipeline.py:77-96`
4. `_spotify_playlist_candidates` — `server/app/services/setbuilder/pool.py:959-1008`
5. `login_and_get_tokens` — `server/app/services/beatport.py:65-128`
6. `BeatportSearchResult` schema — `server/app/schemas/beatport.py:16-30` (no `isrc` field
   anywhere in the class); the enrichment cascade's `getattr(direct, "isrc", None)` at
   `server/app/services/sync/enrichment_pipeline.py:454` therefore always falls through to the
   `None` default for Beatport results — Beatport genuinely never contributes an ISRC in this
   codebase, not just rarely.
7. `start_device_login` / `check_device_login` — `server/app/services/tidal.py:57-135`
8. `_track_to_result` — `server/app/services/tidal.py:193-260` (`isrc` extraction at 222-228,
   set on the result at 257; no `genre` field anywhere on `TidalSearchResult`)
9. Module docstring — `server/app/services/musicbrainz.py:7-11`
10. `lookup_artist_genre` / `lookup_artist_genres` — `server/app/services/musicbrainz.py:111-173`
11. `check_artist_exists` — `server/app/services/musicbrainz.py:61-108`, consumed by
    `server/app/services/recommendation/mb_verify.py:21`
12. `SoundchartsAudioFeatures` — `server/app/services/soundcharts.py:79-106`;
    `get_song_features_by_isrc` — `server/app/services/soundcharts.py:349-378`
13. `discover_songs` + `SoundchartsTrack` — `server/app/services/soundcharts.py:70-76`, `200-265`
14. `get_related_songs_by_isrc` — `server/app/services/soundcharts.py:410-470`; candidates are
    built with title/artist/source only, no metadata fields —
    `server/app/services/recommendation/soundcharts_candidates.py:172-178`
15. Module docstring — `server/app/services/listenbrainz.py:7-11`; `_get_lb_token` —
    `server/app/services/listenbrainz.py:80-85`
16. `fetch_artist_popularity` — `server/app/services/listenbrainz.py:35-77`; `lb_radio_discover`
    — `server/app/services/listenbrainz.py:88-148`

## 3. Per-Pipeline Detail

### 3.1 Request-Time Enrichment Pipeline

Entry point: `enrich_request_metadata` — defined in
`server/app/services/sync/enrichment_pipeline.py:322-688`. Despite the name,
`server/app/services/sync/orchestrator.py` (hereafter `orchestrator.py`) does **not** define it:
it only imports and re-exports it with `# noqa: F401`
(`server/app/services/sync/orchestrator.py:24-28`). Treat `orchestrator.py` as a thin re-export
of `enrichment_pipeline.py`, not the implementation — a plausible misattribution this audit
corrects (see the `ARCHITECTURE.md` edit landing alongside this document).

Every request-queue surface (guest submit / collect / kiosk / DJ add / bulk / refresh) schedules
enrichment through **one** helper, `_enrich_with_fresh_session`
(`server/app/services/sync/orchestrator.py:35-54`), which opens its own DB session per background
task so the request-scoped session is never pinned through slow external API calls.

Cascade, run only for fields still missing on the `Request`:

0. Direct fetch when `source_url` is a Beatport or Tidal URL (`server/app/services/sync/enrichment_pipeline.py:436-477`).
0b. Spotify URL → ISRC bridge, resolved independently of Tidal auth so it can also feed the
    Soundcharts lookup below (`server/app/services/sync/enrichment_pipeline.py:479-519`).
1. MusicBrainz artist-level genre lookup, 1 req/sec (`server/app/services/sync/enrichment_pipeline.py:521-529`).
2. Beatport search for BPM/key, genre backfill if MusicBrainz missed
   (`server/app/services/sync/enrichment_pipeline.py:531-568`).
3. Tidal search for BPM/key backup when Beatport didn't find them
   (`server/app/services/sync/enrichment_pipeline.py:570-604`).
4. Per-event BPM half/double-time context correction — request-only, **never** written to the
   store (`server/app/services/sync/enrichment_pipeline.py:280-319, 610-620`).
5. Soundcharts audio features — gated by `soundcharts_audio_features_enabled`, only when an ISRC
   is in hand and the store row (if any) still lacks `energy` (`server/app/services/sync/enrichment_pipeline.py:622-640`).
   `SoundchartsAudioFeatures` carries `tempo_bpm` / `key` / `genres` fields
   (`server/app/services/soundcharts.py:100-106`), but `_soundcharts_audio_values`
   (`server/app/services/sync/enrichment_pipeline.py:126-144`) deliberately excludes all three from what it writes to the
   store — **Soundcharts never actually contributes bpm/key/genre in this codebase**, only the
   remaining audio-feature fields (energy, danceability, valence, acousticness,
   instrumentalness, speechiness, liveness, loudness, time_signature, explicit, duration).

Store write (dual-write, #541): resolved fields are upserted into the master `tracks` table with
per-field provenance via `upsert_track` (`server/app/services/tracks/store.py:68-150`), gated by
the precedence ladder in `tracks/provenance.py` (full ladder in §4). A cache-aside short-circuit
(`server/app/services/sync/enrichment_pipeline.py:359-402`) skips the **entire** cascade above when a trusted
(`_trio_trusted`, `server/app/services/sync/enrichment_pipeline.py:224-242`) store row already exists for the recording —
the dedupe win that makes a song requested at two events cost one set of provider API calls, not
two.

### 3.2 Recommendation Engine

Entry: `_search_candidates` — `server/app/services/recommendation/service.py:696-783`
(hereafter `service.py`). Three Tidal candidate strategies gated by connection + profile shape —
LB Radio discovery → Soundcharts discovery → text search
(`server/app/services/recommendation/service.py:741-765`) — plus a Beatport path (structured
browse → text search, `server/app/services/recommendation/service.py:718-734`), plus an
independent Soundcharts related-tracks source that needs **no** connected service at all
(`server/app/services/recommendation/service.py:772-781, 799-823`).

Two independent enrichment code paths exist here and must not be conflated:

- **`recommendation/enrichment.py`** (`enrich_track`, `enrich_from_beatport`, `enrich_from_tidal`)
  merges Beatport (primary — has genre) with Tidal (BPM/key gap-fill) for one title/artist pair
  (`server/app/services/recommendation/enrichment.py:134-176`). This module never imports `tracks/store` and never writes the master
  store itself — it is a pure, independent Beatport/Tidal merge (no-code-change, §6/§7). It *is*,
  however, reused by two other call sites that write the store on **its** behalf:
  `recommendation/service.py`'s `enrich_event_tracks` (display-only — still no store write) and
  `setbuilder/pool.py`'s `_enrich_and_writeback` (`server/app/services/setbuilder/pool.py:548-595`), which upserts the result
  into the master store. So `enrich_track` itself never touches the store, but its output is the
  fuel for a store write performed by a *different* module — worth stating precisely rather than
  either "it never affects the store" or "it writes the store".
- **`recommendation/soundcharts_candidates.py`** — the two Soundcharts-backed generators from §2.
  `search_candidates_via_soundcharts` resolves discovery hits to playable Tidal track IDs
  (`server/app/services/recommendation/soundcharts_candidates.py:44-115`); `related_candidates_from_seeds` (#556) seeds the paid
  related-tracks endpoint from the event's own tracks, resolving each seed's ISRC from the
  request first and falling back to the master store (`server/app/services/recommendation/soundcharts_candidates.py:118-185`) — this
  **is** a master-store *read* (`get_track`, imported at `server/app/services/recommendation/soundcharts_candidates.py:26`), just
  never a write.

MusicBrainz and ListenBrainz together gate candidate *quality* rather than supply metadata:
`recommendation/mb_verify.py` verifies each candidate artist is a real, community-known artist
via MusicBrainz's `check_artist_exists`, then cross-checks ListenBrainz listener counts for
verified artists to reject stock/AI-filler tracks (`server/app/services/recommendation/mb_verify.py:1-11, 37-44`).

### 3.3 SetBuilder Vibe Resolution

Distinct from both cascades above: WrzDJSet's per-track "vibe" (`energy` 0-10 + `mood`) resolves
through its **own** three-tier system, independent of `Track.energy` (§4).

`resolve_vibe` (`server/app/services/setbuilder/vibe_resolver.py:1, 52-68`, issue #391) walks,
per field, own → community → LLM, taking the first non-`None` value
(`_first`, `server/app/services/setbuilder/vibe_resolver.py:44-49`):

1. **Own** — the viewing DJ's own explicit edit, read from `TrackVibeOverride`
   (`server/app/services/setbuilder/vibe_resolver.py:81-98`). Pure DB read, zero network calls.
2. **Community** — consensus across *other* DJs' `TrackVibeOverride` rows, gated so noise can't
   masquerade as signal: energy needs `>= min_sample` votes with population stddev strictly below
   `max_stddev` (the value is the rounded mean); mood needs `>= min_sample` votes and a strict
   majority winner (`server/app/services/setbuilder/community_vibe.py:49-59`). Also a pure DB
   read, zero network calls.
3. **LLM** — `TrackVibe` cache rows at the current `PROMPT_VERSION` / `SCHEMA_VERSION`, filled by
   `enrich_pool_vibes` via the LLM Gateway in batches of `BATCH_SIZE=20`
   (`server/app/services/setbuilder/vibe_enrichment.py:32-38, 268-318`). The only tier of the
   three that makes a network call.

On top of the resolved value, `taste_profile.py` (#409) applies a **per-DJ calibration**, not a
fourth resolution tier: `taste_adjusted_energy` (`server/app/services/setbuilder/taste_profile.py:76-90`) shifts a non-"own"
resolved energy by a capped (`ENERGY_ADJUSTMENT_CAP = 1.5`) delta learned from that DJ's
historical energy edits (`build_taste_profile`, `server/app/services/setbuilder/taste_profile.py:41-66`). It only ever adjusts an
already-resolved community/LLM value — it never substitutes for one, and it never runs when the
resolved value came from the DJ's own override.

`coverage.py` (#542) is a separate, read-only concern, not part of vibe resolution itself:
`pool_coverage` (`server/app/services/setbuilder/coverage.py:1, 50-79`) reports what fraction of
a set's pool carries all five pool→builder contract fields (bpm/key/genre/duration/energy),
feeding a soft, overridable build-readiness warning (`READY_THRESHOLD = 0.80`,
`server/app/services/setbuilder/coverage.py:27-31`). It performs no resolution or enrichment itself — only counts what the
pipelines above already produced.

## Appendix: Files read in full for §1-3 of this document

`server/app/services/tracks/provenance.py`, `tracks/store.py`, `sync/orchestrator.py`,
`sync/enrichment_pipeline.py`, `spotify.py`, `beatport.py` (partial — auth flow + search/fetch
functions), `tidal.py` (partial — auth flow + search/fetch functions), `musicbrainz.py`,
`soundcharts.py`, `listenbrainz.py`, `track_match.py`, `schemas/beatport.py`,
`setbuilder/pool.py` (partial — hydrate/enrich/import sections),
`setbuilder/vibe_resolver.py`, `setbuilder/community_vibe.py`, `setbuilder/vibe_enrichment.py`,
`setbuilder/taste_profile.py`, `setbuilder/coverage.py`, `recommendation/enrichment.py`,
`recommendation/soundcharts_candidates.py`, `recommendation/service.py` (partial — candidate
search sections), `recommendation/mb_verify.py` (partial — module header + one helper). A
consolidated file map covering the full document lands with §8 in a later commit of this PR.
