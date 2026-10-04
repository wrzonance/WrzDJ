# Bridge protocol update plan

1. **Shapes/interfaces:** replace the ambient event-emitter logger type with the
   five-method upstream interface and optional `StageLinqOptions.logger`. Each
   plugin run owns a logger deactivation callback; public plugin events stay the
   same. Both manifests gain registry-backed AlphaTheta dependency overrides.
2. **Change map:** both package manifests/locks; StageLinq plugin, declarations,
   plugin tests and real-library contract tests. The Electron app imports the
   shared plugin and keeps protocol dependencies external to its Vite bundle.
3. **Disposable spike:** clean npm probes with explicit registry dependencies
   install successfully; scoped overrides remove the local links. No probe code
   is retained in the repository. Published logger source confirms injection must
   precede singleton/device access. Baseline: all 36 contract/plugin tests pass.
4. **Invariants/red:** add tests for five-level log forwarding, silence after stop
   and no old-run logs after restart. Update the contract to the documented new
   API and test real adapter startup with only network methods stubbed. Confirm
   failure against the old adapter, including after dependency installation.
5. **Green:** inject the logger, deactivate it on stop, update declarations and
   regenerate npm locks. Preserve options and all unrelated event behavior.
6. **Validation/integration:** clean npm installs and graphs, TypeScript, coverage,
   native SQLite and packaged app smoke tests, audits with findings triaged. Push
   reused PR #683, validate latest-head CI, perform one final adversarial review,
   address valid findings without a second review, merge pinned SHA and verify
   main. Record supersession/issue dispositions and refresh the queues.

Packaging validation exposed #723. Before integration, pin the actual Electron
ABI failure with `scripts/test-bridge-app-package.cjs`, then move staged externals
to the package root in `packageAfterCopy`. Repackage and require the same smoke
to pass. Add that boundary check to the existing bridge-app CI job. No new data
shapes/interfaces: only the standard module directory moves; source staging stays
unchanged. The existing package served as the disposable layout probe and the
failing artifact; implementation uses Forge's verified hook order.
