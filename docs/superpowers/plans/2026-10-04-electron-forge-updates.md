# Electron and Forge implementation plan

1. Structs/interfaces: preserve Forge config, packaged manifest and preload API
   shapes; only adjust version/output contracts required by the upgrade.
2. Map changes: bridge-app manifest/lock, Forge/Vite config if needed, main preload
   path, package smoke test, release compatibility docs and audit disposition.
3. Spike: install current Electron 44/Forge 8/fast-uri 4; exercise type checking,
   package and AppImage creation. Record actual migration failures. Revert any
   speculative workaround before implementing the smallest proven fix.
4. Invariants/TDD: pin real missing-entry/preload regressions at the packaged
   artifact or Electron boundary; demonstrate failure before entry-path fixes.
   Existing settings tests plus an actual settings-validator probe cover fast-uri.
5. Implement compatibility fixes; clean npm install and graph, app/bridge types
   and suites with coverage, Linux package/native smoke, AppImage make, audit.
6. Push reused draft PR; latest-head CI; one final cross-provider review; verify
   findings, fix valid defects without a second review; SHA-pinned merge and main
   checks. Refresh six queues and retain dashboard #588 for remaining work.
