# Bridge dependency audit disposition — 2026-10-04

After the Electron 44/Forge 8 upgrade, npm audit reports three affected package
nodes in `bridge` and seven in `bridge-app` (one moderate, six high; counts include
dependent packages). The app count fell from 29 to seven.
These are **not clean audits**. CI still runs the existing audit commands; their
pre-existing `continue-on-error` settings are unchanged. The following findings
were checked against the installed graph and current application call sites.

| Package/advisory | Exposure and disposition | Follow-up |
| --- | --- | --- |
| `ip` — [GHSA-2p57-rm9w-gvfp](https://github.com/advisories/GHSA-2p57-rm9w-gvfp) | StageLinq calls only `subnet` on OS network-interface addresses/netmasks in `network/announce.js` and `eaas/discoverer.js`. Neither the library nor WrzDJ calls the affected `isPublic`/`isPrivate` classification functions. No patched release is available. The runtime dependency remains, but this vulnerable operation is not used. | Recheck on the next StageLinq release or by 2026-11-04; prefer an upstream replacement of `ip`. |
| `file-type` — [GHSA-5v7r-6r5c-r473](https://github.com/advisories/GHSA-5v7r-6r5c-r473) | StageLinq's `NetworkDevice.addSource` and `dumpAlbumArt` contain the `fromBuffer` calls. WrzDJ invokes neither method. Database auto-download remains explicitly disabled; file transfer remains enabled for metadata. A blind override to the patched 21.x release would replace the old CommonJS API. | Recheck on the next StageLinq release or by 2026-11-04, and before enabling database/art parsing. Prefer the upstream parser upgrade. |
| `image-size` — [GHSA-w3rx-r6r6-pgpr](https://github.com/advisories/GHSA-w3rx-r6r6-pgpr) | `appdmg` invokes the parser only for a configured background image. WrzDJ's MakerDMG config supplies a name/icon and no background; icons are copied without that parser. It is absent from the packaged runtime. The patched 2.x API is incompatible with the old callback consumer. | Rechecked appdmg 0.6.6 source in its official npm archive because this optional macOS package is not installed on Linux. Revisit by 2026-11-04 and before adding a background; Forge 8 does not fix this chain. |

The regenerated app lockfile no longer contains `braces`, the unscoped
`extract-zip`, `http-cache-semantics`, or Got. Forge 8 replaces old Packager
tooling; a scoped, AppImage-tested maker-base 8 override also removes the legacy
Forge 7 dependency tree. The maintained `@electron-internal/extract-zip` package
is a separate build dependency, not an ignored instance of the old package.
No npm audit suppression was added. The historical shared-cache disposition and
Dependabot alert #342 receipt remain in PR #715.

The packaged Electron 44.5.1 smoke exercises all four pinned protocol packages
and native SQLite with ABI 149. The renderer/preload smoke also checks IPC,
invalid settings filtering and persistence across two real launches in an
isolated profile. Archive inspection confirms `ip`/`file-type` remain while
`braces`, `extract-zip`, `http-cache-semantics` and `image-size` are absent.
This establishes packaging scope, not a
claim that vulnerable package versions have been patched or that hardware
integration has been tested. Reevaluate these dispositions if call sites,
configuration, packaging, or upstream dependencies change.
