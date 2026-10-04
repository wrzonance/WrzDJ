# Bridge protocol dependency updates

Track dependency drift #690 and release notices #691, #692, #694 and #695.
Reuse Renovate PR #683 and incorporate #681/#682 plus the queued OneLibrary update
from dashboard #588. No overlap with excluded PR #714 or issue #713.

## Evidence and design

StageLinq 3.5.7 exposes an injected logger with `trace`, `debug`, `info`, `warn`
and `error` methods. The existing adapter calls the removed event-emitter API.
Inject a forwarding logger before accessing devices, preserving level names and
argument formatting. Deactivate each logger when that run stops, so callbacks
from a stopped run cannot leak into a later run. Preserve file transfer enabled,
database auto-download disabled, existing device events and the connect timeout.

AlphaTheta 0.28.5 publishes `file:../metadata-connect` and
`file:../onelibrary-connect` dependencies. A disposable npm probe verified that
explicit registry dependencies plus scoped `$dependency` overrides produce a
lockfile with registry integrity hashes and no local links. Apply that strategy
to both consumers. Pin AlphaTheta 0.28.5, StageLinq 3.5.7, metadata-connect 1.2.2
and onelibrary-connect 1.1.6; preserve the existing security overrides.

Sources: official npm manifests and published StageLinq `types/logger.d.ts` and
`StageLinq/index.js`; upstream release notes linked in PRs #681–683. All three
PRs are Renovate-authored; comments/reviews contain no other actionable feedback.
Issue #690 has no Project item, so board movement is a no-op.

## Verification

The real-library contracts must validate the new logger interface and successful
adapter startup without opening network sockets. Plugin tests must cover all five
levels, silence after stop and isolation after restart. Retain device event and
option invariants. Regenerate both locks with npm, then run clean installs,
TypeScript, full coverage suites and dependency audits for both consumers.
Smoke-test the native SQLite dependency and packaged Electron output; no hardware
availability or real-device behavior is claimed from mocked network calls.

One final cross-provider review follows latest-head technical CI. Merge only the
tested SHA, verify main and close superseded PRs/release issues with evidence.
Keep dashboard #588 open and scanners enabled.

## Packaged native runtime prerequisite (#723)

The first artifact smoke failed: copied SQLite targets Node ABI 137, while the
packaged Electron requires ABI 146. Forge's Vite plugin excludes root
`node_modules`, and our helper stages externals below `.vite/build`; Forge's
normal rebuild consequently misses them. Its documented `packageAfterCopy` hook
runs before the existing native rebuild. Move the staged tree to the package
root there, using normal Node module resolution and Forge's own rebuild logic.
No custom rebuild dependency or host-checkout mutation is needed.
Refresh the existing `node-abi` 3.x dependency to at least 3.96.0: the previous
3.87.0 table cannot identify Electron 42's ABI. Keep the override scoped to 3.x.

The new artifact regression launches the packaged executable in Electron's Node
mode, verifies dependency versions and resolution inside the archive, exercises
logger injection, and opens native in-memory SQLite through each protocol
consumer. It fails on the original package. Run it in CI after unit tests, so
successful packaging alone cannot hide another ABI mismatch. Hardware testing
remains outside this automated check.

Existing npm audit findings are documented with reachability evidence and review
dates in `docs/security/dependency-audit-2026-10-04.md`; the audits are not reported
as passing simply because the workflow tolerates their exit status.

A final registry check found AlphaTheta 0.28.5. Its published package changes
streaming title/artist fallback and leaves dependencies/API exports unchanged;
include that patch so the drift closure targets the latest checked version.
The GitHub latest-release endpoint returned 404; the official npm tarball diff
provides the patch evidence instead.
