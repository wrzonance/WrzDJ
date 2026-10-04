# Bridge dependency audit disposition — 2026-10-04

The protocol updates retain the existing npm audit findings: three affected
package nodes in `bridge`, 29 in `bridge-app` (counts include dependent packages).
These are **not clean audits**. CI still runs the existing audit commands; their
pre-existing `continue-on-error` settings are unchanged. The following findings
were checked against the installed graph and current application call sites.

| Package/advisory | Exposure and disposition | Follow-up |
| --- | --- | --- |
| `ip` — [GHSA-2p57-rm9w-gvfp](https://github.com/advisories/GHSA-2p57-rm9w-gvfp) | StageLinq calls only `subnet` on OS network-interface addresses/netmasks in `network/announce.js` and `eaas/discoverer.js`. Neither the library nor WrzDJ calls the affected `isPublic`/`isPrivate` classification functions. No patched release is available. The runtime dependency remains, but this vulnerable operation is not used. | Recheck on the next StageLinq release or by 2026-11-04; prefer an upstream replacement of `ip`. |
| `file-type` — [GHSA-5v7r-6r5c-r473](https://github.com/advisories/GHSA-5v7r-6r5c-r473) | StageLinq's `NetworkDevice.addSource` and `dumpAlbumArt` contain the `fromBuffer` calls. WrzDJ invokes neither method. Database auto-download remains explicitly disabled; file transfer remains enabled for metadata. A blind override to the patched 21.x release would replace the old CommonJS API. | Recheck on the next StageLinq release or by 2026-11-04, and before enabling database/art parsing. Prefer the upstream parser upgrade. |
| `braces` — [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) | Build tooling receives repository-controlled glob patterns, including Forge's fixed `.bin` cleanup pattern. It is absent from the packaged runtime. No patched release is available. | Reassess in the planned Forge upgrade and by 2026-11-04; do not expose arbitrary glob input. |
| `extract-zip` — [GHSA-jmr9-qjv8-65gv](https://github.com/advisories/GHSA-jmr9-qjv8-65gv), [GHSA-7pqw-9j4j-h8q3](https://github.com/advisories/GHSA-7pqw-9j4j-h8q3) | The installed consumer is Electron Packager. Its archive input is the Electron release downloaded by `@electron/get`, whose checksum verification remains enabled. WrzDJ has no arbitrary ZIP import through this package, and it is absent from the packaged runtime. No patched release is available. This assessment assumes trusted official Electron releases, not arbitrary archives or replacement mirrors. | Reassess in the Forge/Packager upgrade and by 2026-11-04; keep checksum validation enabled. |
| `http-cache-semantics` — [GHSA-ch52-4w7c-c8xp](https://github.com/advisories/GHSA-ch52-4w7c-c8xp) | Development-only consumers do not provide the affected shared authenticated-response cache: Got caching is disabled by default; `make-fetch-happen` sets `shared: false` and checks `storable()`. It is absent from the packaged runtime. The prior detailed disposition is in PR #715; Dependabot alert #342 was dismissed as `not_used`. Merely installing 4.3.0 is not claimed as a fix. | Recheck during the Forge upgrade, before adding cache usage, or by 2026-11-04. |
| `image-size` — [GHSA-w3rx-r6r6-pgpr](https://github.com/advisories/GHSA-w3rx-r6r6-pgpr) | `appdmg` invokes the parser only for a configured background image. WrzDJ's MakerDMG config supplies a name/icon and no background; icons are copied without that parser. It is absent from the packaged runtime. The patched 2.x API is incompatible with the old callback consumer. | Recheck the DMG dependency chain by 2026-11-04 and before adding a background. Forge 8 alone must not be assumed to fix this chain. |

The packaged Electron smoke exercises all four pinned protocol packages and
native SQLite. Archive inspection confirms `ip`/`file-type` remain while the four
build-only packages above are absent. This establishes packaging scope, not a
claim that vulnerable package versions have been patched or that hardware
integration has been tested. Reevaluate these dispositions if call sites,
configuration, packaging, or upstream dependencies change.
