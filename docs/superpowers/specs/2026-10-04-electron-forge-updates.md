# Electron and Forge dependency upgrade

Tracked by dependency dashboard #588; reuse Renovate PR #725. Base: `9046d6eb`.

Upgrade Electron to the current stable 44.x release and Forge to 8.0.1, together
with the queued fast-uri 4 update used by the settings validator. Keep the existing
protocol versions, security settings, installer formats and release platforms.
Regenerate the npm lockfile normally, without forced peer installation.

Official Forge 8 changes its main/preload output names to `.cjs` and publishes
ES modules. Update the application's entry contracts to match actual generated
artifacts. Verify the AppImage maker against Forge 8 by producing an installer;
its dependency on maker-base 7 alone does not establish incompatibility.
Use a scoped maker-base 8 override only after validating the maker's public API
and actual AppImage output; remove the obsolete Forge 7 tooling graph this way.

Invariants: the packaged manifest resolves to a real entry; the preload exposes
the existing bridge API; native SQLite loads in the packaged Electron runtime;
settings validation/persistence still works; current tests and coverage gates
pass; the shipped app retains only its intended runtime dependencies. Do not
claim macOS/Windows execution from Linux packaging evidence.

A Playwright Core dev dependency drives two actual packaged Electron launches
with an isolated temporary profile. Check preload IPC, invalid settings filtering,
and persistence after restart. CI supplies its documented Xvfb virtual display;
no browser download is needed. The existing native smoke remains a separate gate.

Reassess every existing npm-audit disposition against the regenerated graph and
packaged artifact. Document unresolved findings rather than suppressing them.
Electron 44 requires macOS 13+ and drops Windows ia32/Linux armv7l; current release
targets are x64 and macOS arm64, so retain those targets and document the macOS
minimum. Dashboard TypeScript 7 remains a separate upstream compatibility blocker.

Sources: official Electron 44 release/breaking-change notes; Forge v8.0.1 release
and Vite plugin source; npm manifests for Electron, Forge and the AppImage maker.

https://www.electronjs.org/blog/electron-44-0
https://www.electronjs.org/docs/latest/breaking-changes
https://github.com/electron/forge/releases/tag/v8.0.1
