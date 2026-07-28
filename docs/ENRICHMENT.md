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

## 4. Source-of-Truth Matrix

The precedence ladder (`server/app/services/tracks/provenance.py:12-25`, verified live this
session) is the same numeric scale for every master-store field:

| Source | Precedence | Notes |
|---|---|---|
| `manual` | 100 | Highest trust. **No live call site writes this** — reserved for a future DJ manual-edit endpoint; not reachable today. |
| `lexicon` | 90 | **Reserved, unwired** — issue #526's landing slot. No `lexicon.py` client exists yet. |
| `soundcharts` | 50 | Tied with beatport/tidal/musicbrainz. |
| `beatport` | 50 | Tied. |
| `tidal` | 50 | Tied. |
| `musicbrainz` | 50 | Tied. Cache-authoritative floor (`CACHE_TRUST_FLOOR = 50`, `provenance.py:44`) — only 50+ sources can short-circuit re-enrichment. |
| `community` | 40 | **No live call site writes this to `Track.*`** — the string exists for `TrackVibe`'s own separate community tier (§3.3), never as a `Track` provenance source. |
| `legacy` | 30 | Pre-store backfill from existing `Request` columns (#541) — used by `sync/enrichment_pipeline.py:265` and `server/app/scripts/backfill_tracks.py:76`. |
| `llm` | 10 | **No live call site writes this to `Track.*`** — reserved; `TrackVibe`'s own LLM tier (§3.3) is a separate system. |
| unknown/missing | 0 | `precedence()` default (`provenance.py:36`). |

`upsert_track` (`server/app/services/tracks/store.py:68-150`) enforces this via
`should_overwrite`: `precedence(new) >= precedence(existing)`, so **a tie overwrites** — the
guard against equal-precedence churn between Beatport and Tidal (or MusicBrainz and Beatport) is
therefore not a ladder property, it's the pipeline's own cascade order (`if not request.bpm`-
style guards at `server/app/services/sync/enrichment_pipeline.py:532, 571`; the code comment at
624-625 literally reads "avoid equal-precedence churn" for the parallel Soundcharts case).
`ISRC` is not gated by this ladder at all — see its row below.

| Field | Precedence / resolution | WrzDJSet boundary | Evidence |
|---|---|---|---|
| `genre` | MusicBrainz-first (artist-level), Beatport backfill only if MusicBrainz missed — both tier 50, order-guarded not precedence-driven | Same master-store value; SetBuilder never re-resolves genre itself | `enrichment_pipeline.py:521-568` |
| `bpm` | Beatport-first, Tidal backup only if Beatport missed — both tier 50, order-guarded | Same master-store value; pool import/hydration reads it, never re-derives it | `enrichment_pipeline.py:531-604` |
| `musical_key` | Same cascade as bpm (Beatport-first, Tidal backup) | Same as bpm | `enrichment_pipeline.py:531-604` |
| `isrc` | **Not precedence-gated.** An identity field on `TrackIdentity`, not a `values`/provenance field: backfilled onto a signature-matched row only if currently `NULL` (`store.py:133-135`), never overwritten once set. A conflicting incoming ISRC on an existing row is refused outright rather than resolved by precedence (`store.py:112-131`) | Same identity field; pool import's `_hydrate_one` resolves by ISRC-then-signature exactly like the request path | `store.py:68,108-135` |
| `Track.energy` | Numeric-precedence ladder above. **Only two sources are live today**: `soundcharts` (tier 50, request-time audio-features step, gated) and `legacy` (tier 30, backfill). `lexicon` (90) is reserved/unwired (#526); `manual`/`community`/`llm` (100/40/10) exist in the ladder but have zero live `Track.*` writers. Soundcharts also supplies `danceability`, `valence`, `acousticness`, `instrumentalness`, `speechiness`, `liveness`, `loudness`, `time_signature`, `explicit`, `duration` in the same call — footnoted here, not separate matrix rows (§1 field scope) | Read via `pool.hydrate_candidates_from_store` (§5); WrzDJSet does not write `Track.energy` itself | `models/track.py:31,46-48`; `provenance.py:12-25`; `enrichment_pipeline.py:622-640`; `pool.py:580` (`_enrich_and_writeback` only ever passes `"beatport"`\|`"tidal"`\|`"legacy"`, never energy) |
| `TrackVibe.energy` | **Not the precedence ladder at all** — a genuinely separate three-tier system: own-DJ override → community consensus → LLM cache, first non-`None` wins (§3.3) | This **is** WrzDJSet's local-override tier, live today: tiers 1-2 (own, community) are zero-network DB reads; only tier 3 (LLM) calls out | `vibe_resolver.py:44-68`; `community_vibe.py:49-59`; `vibe_enrichment.py:32-38` |

## 5. Cloud-only vs. Cloud+Optional-Local Boundary

**(a) WrzDJ request-queue is 100% cloud.** Every field in §4 above resolves through Beatport,
Tidal, MusicBrainz, or Soundcharts — all external HTTP APIs (`enrichment_pipeline.py:322-688`).
No local/offline resolution path exists in this pipeline, and none is proposed by this document;
the request queue is not in #526's scope.

**(b) WrzDJSet is cloud-primary with a local override tier already live, plus a reserved second
one.**

- **Cloud-primary base**: pool candidates hydrate from the master `tracks` store —
  `hydrate_candidates_from_store` (`server/app/services/setbuilder/pool.py:262-321`) — which is
  itself populated by the same cloud providers as §4/§5(a). When the store misses and a genuine
  gap remains, it falls through to the provider cascade (`enrich_track`, step 4 of the docstring
  at `pool.py:270-289`) — still cloud.
- **Already-live local override**: `TrackVibe.energy`'s own→community tiers
  (`vibe_resolver.py:81-98`, `community_vibe.py:49-59`) resolve entirely from DB rows written by
  DJs' own edits/votes — **zero network calls**, and they take priority over the LLM tier. This
  is a real, shipping local-override mechanism today, not a future one.
  `taste_profile.py`'s per-DJ calibration (§3.3) layers on top of it, also DB-only.
  `coverage.py` (§3.3) reports on the *result* of this resolution; it performs no resolution
  itself.
- **Reserved, not-yet-wired local slot**: `"lexicon": 90` in `Track.energy`'s precedence ladder
  (`provenance.py:14`) sits above every cloud source (50) and below only `manual` (100) — a
  measured-local-source tier that outranks all cloud providers by design, but has no client
  module wired to fill it yet (§2). This is issue #526's literal plug-in point: when a
  `lexicon.py` adapter lands and calls `upsert_track(..., sources={"energy": "lexicon"})`, it
  slots into the existing ladder with no other code change required.

## 6. Provider Fate Recommendations

**This section makes recommendations only** — no provider is removed, refactored, or
reconfigured as a result of this document (§1). Every row below states a proposal for future
work, phrased as "recommend," not as work already performed.

| Provider / code path | Recommendation | Rationale | Evidence |
|---|---|---|---|
| Spotify | keep | Issue #527's own recon described Spotify as "now only an ISRC bridge" — this audit found **3 confirmed live roles**, not one: (1) client-credentials search, (2) ISRC bridge, (3) public-playlist-import resolving ISRC/duration/artwork. Recommend keeping all three; none is dormant. | `spotify.py:54-98` (search); `enrichment_pipeline.py:77-96` (`_get_isrc_from_spotify`); `pool.py:959-1008` (`_spotify_playlist_candidates`) |
| Beatport | keep | Primary bpm/key/genre source across request-time enrichment, recommendation-engine gap-fill, and pool hydration; per-DJ OAuth. | `beatport.py:65-128`; `provenance.py:16` |
| Tidal | keep | bpm/key/ISRC backup across the same three pipelines; per-DJ OAuth device flow. | `tidal.py:57-135`; `provenance.py:17` |
| MusicBrainz | keep | Narrow, well-scoped genre-only artist-level utility, plus a candidate-quality gate for recommendations (not a metadata field supplier there). No API key required. | `musicbrainz.py:111-173`; `mb_verify.py:21` |
| Soundcharts | keep | Already formalizing — merged PR #560 (closed #556) wired a second live recommendation-candidate generator on top of the existing audio-features gate; this is active, ongoing investment, not dormant wiring #527 asked us to reconsider. | `soundcharts.py:358,423`; `soundcharts_candidates.py:44-185`; PR #560 (merged 2026-06-25) |
| ListenBrainz | keep | Candidate-discovery (LB Radio) plus an artist-popularity junk filter; app-level token, never supplies genre/bpm/key/ISRC/energy so it can't conflict with the ladder above. | `listenbrainz.py:35-148` |
| `recommendation/enrichment.py`'s independent Beatport/Tidal merge | no-change | Never imports `tracks/store` and never writes the master store itself (§3.2) — a real, documented duplication of logic that also exists in `enrichment_pipeline.py`'s cascade, but consolidating it is exactly the "provider-strategy abstraction" #527 asks us to *consider*, not build here. See §7(a)/(c). | `recommendation/enrichment.py:134-176` |
| `search_candidates_via_soundcharts` (discovery call site) | no-change | Only Soundcharts call site with no explicit enable flag (credential-presence-gated only), unlike its two sibling call sites which are both dark-by-default behind a boolean setting. Documented, not fixed here. See §7(b). | `soundcharts.py:212-215`; `recommendation/service.py:754-756` |

## 7. Open Follow-ups

Real inconsistencies and open questions this audit found and documents. **None of these is fixed
by this PR** — every entry below states its own "not fixed here."

- **(a) `recommendation/enrichment.py` bypasses the master tracks store.** `enrich_track` merges
  Beatport/Tidal directly for one title/artist pair and never touches `tracks/store` — its output
  only reaches the store when a *different* caller (`pool.py`'s `_enrich_and_writeback`) chooses
  to upsert it. This is a real second, independent enrichment implementation alongside
  `sync/enrichment_pipeline.py`'s cascade. **Not fixed here** — consolidating the two is future
  work (see §7(c)). Evidence: `recommendation/enrichment.py:134-176`,
  `setbuilder/pool.py:548-595`. Suggested labels: `refactor`, `area:recommendation`.
- **(b) `search_candidates_via_soundcharts` has no feature flag.** Its two sibling Soundcharts
  call sites (`get_song_features_by_isrc`, `get_related_songs_by_isrc`) are both dark-by-default
  behind an explicit boolean setting; this one is gated only by credential presence. **Not fixed
  here** — adding a matching `soundcharts_discovery_enabled`-style flag is a one-line follow-up,
  deliberately left undone so this PR stays docs-only. Evidence: `soundcharts.py:212-215`,
  `recommendation/service.py:754-756`, `core/config.py:131-141` (the two sibling flags this one
  lacks). Suggested labels: `enhancement`, `area:recommendation`.
- **(c) Provider-strategy abstraction — defer, do not build in parallel with #544.** Issue
  #527's scope item 4 asks us to consider a clean provider interface + priority order if the
  audit shows the ad-hoc chain is a maintenance cost. This audit found real duplication (7(a)
  above, plus the ladder's tie-break-by-cascade-order behavior in §4) that would benefit from
  one. However, **#544 is open and already in progress on this exact code** — an external
  audio-features provider behind a "clean interface, config-gated" abstraction feeding
  `Track.energy`, using the very `lexicon`-reserved slot this document maps in §5(b). Proposing a
  second, competing abstraction here would collide with #544 mid-flight. **Recommend: defer —
  in progress on #544** — revisit a broader provider-strategy abstraction only after #544 lands.
  **Not fixed here**; no redesign is proposed by this document. Evidence: `provenance.py:14`
  (the `lexicon` slot #544 targets), `enrichment_pipeline.py:531-604` and
  `recommendation/enrichment.py:134-176` (the two independent Beatport/Tidal merges motivating
  the question). Suggested labels: `research`, `blocked`.
- **(d) Soundcharts related-tracks paid-tier cost is an open business decision, not a code gap.**
  `soundcharts_related_tracks_enabled` defaults to `False` specifically because the endpoint is
  paid-tier and no plan is provisioned yet — the config comment states this explicitly. **Not
  fixed here** — this is a spend decision for a human, not something a docs PR or code change can
  resolve. Evidence: `core/config.py:138-141`. Suggested labels: `business-decision`,
  `area:recommendation`.

## 8. Appendix: File Map

Every file read in full or in relevant part while writing this document, grouped by area.

**Precedence & store**
`server/app/services/tracks/provenance.py` (full — `SOURCE_PRECEDENCE` ladder),
`server/app/services/tracks/store.py` (full — `upsert_track`/`get_track`/`should_overwrite`),
`server/app/models/track.py` (partial — energy/danceability/valence columns),
`server/app/scripts/backfill_tracks.py` (partial — `"legacy"` source usage).

**Request-time enrichment**
`server/app/services/sync/orchestrator.py` (full), `server/app/services/sync/enrichment_pipeline.py`
(full), `server/app/core/config.py` (partial — Soundcharts settings).

**Provider clients**
`server/app/services/spotify.py` (full), `server/app/services/beatport.py` (partial — auth +
search/fetch), `server/app/services/tidal.py` (partial — auth + search/fetch),
`server/app/services/musicbrainz.py` (full), `server/app/services/soundcharts.py` (full),
`server/app/services/listenbrainz.py` (full), `server/app/services/track_match.py` (full),
`server/app/schemas/beatport.py` (partial — result schema).

**Recommendation engine**
`server/app/services/recommendation/enrichment.py` (full),
`server/app/services/recommendation/soundcharts_candidates.py` (full),
`server/app/services/recommendation/service.py` (partial — candidate search sections),
`server/app/services/recommendation/mb_verify.py` (partial — module header + one helper).

**SetBuilder / WrzDJSet**
`server/app/services/setbuilder/pool.py` (partial — hydrate/enrich/import/playlist-import
sections), `server/app/services/setbuilder/vibe_resolver.py` (full),
`server/app/services/setbuilder/community_vibe.py` (full),
`server/app/services/setbuilder/vibe_enrichment.py` (partial),
`server/app/services/setbuilder/taste_profile.py` (partial),
`server/app/services/setbuilder/coverage.py` (partial).

**GitHub issues/PRs cited.** #526, #541, #542, #551, #552, #554, #556, #563 are cited as they
appear in code comments at the file:line evidence above (not independently re-verified against
live GitHub state this session). #527 (this issue), #544, and #560 **were** independently checked
live via `gh issue view` / `gh pr view` this session: #527 is open; #544 is open, 2 comments, in
progress; #560 is a merged PR (2026-06-25) that closed #556 — its own recommendation-candidate
work is complete, but it does not touch the broader provider-strategy question §7(c) defers to
#544.
