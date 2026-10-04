# JavaScript toolchain refresh

Track dashboard #588 and reuse Renovate PR #680. Include #689 (DOM matchers)
and #724 (Node types). Resolve #688 if its sole consumer is removed with proof
that active lint checks are preserved. Excluded kiosk PR #714/#713 is untouched.

## Design and evidence

Refresh the shared test stack to Vitest/coverage 5.0.3, Vite 8.3.2, jest-dom 7.0.1
and jsdom 30.1.2. Align development and CI on Node 24 (minimum 24.15, or Node 26+)
for the published engine requirements. Update related tooling patches: globals,
Node types, browserslist, tsx and esbuild. jsdom 30 requires Undici 8, so update
that override together and validate every remaining consumer.

The dashboard's effective baseline has 60 active lint rules and no active
`react/` or `react-hooks/` rules. Repository searches found no inline directives
enabling those rules. Remove the unused plugin registrations/dependencies and
their disabled rules; this permits ESLint 10 without overriding React's peer
constraint. `eslint-plugin-react-hooks` is the sole installed consumer of
`@babel/core`; if the regenerated graph confirms its absence, remove the unused
Babel override and resolve its major-update PR as no longer applicable.
Preserve every active baseline rule; accept the new recommended ESLint checks.

Use TypeScript ESLint 8.71.0. Its published TypeScript peer range is
`>=4.8.4 <6.1.0`; a disposable npm probe must demonstrate the TypeScript 7
conflict. Keep the dashboard's existing compiler until upstream supports 7;
do not bypass peer resolution. Evaluate TypeScript 7.0.2 for the bridge consumers
with full type checks and actual Forge packaging. Record any real blocker.

Sources: official npm manifests, the installed effective ESLint configuration,
[ESLint 10 migration](https://eslint.org/docs/latest/use/migrate-to-10.0.0),
and [Vitest 5 migration](https://vitest.dev/guide/migration/).
Vitest changes mock clearing, matcher types and coverage path matching. Fix
actual failures without dropping tests, suppressing assertions or lowering gates.

## Validation and integration

Baseline dashboard lint, types and 1453 tests pass (79.70% statements); bridge
392 and app 78 tests passed on main a236d0c7. Compare active lint rules and covered
source file sets after upgrading. Run clean npm installs, complete graphs,
audits, all three type/coverage suites, dashboard production build, packaged
Electron smoke, actionlint and workflow pin tests. Add regression coverage first
for any required behavior fix. Preserve all security overrides unless a verified
consumer migration or graph removal makes one obsolete. One final cross-provider
review follows latest-head CI; merge the tested SHA and verify main. Keep #588
open, and record unsupported updates explicitly rather than hiding them.

## Migration results

Clean installs and complete graphs pass. All 60 baseline lint rules retain their
severity; three recommended rules are added. ESLint's new relational-comparison
option defaults off (that branch did not exist in 9.x), while restricted-global
checking becomes stricter. The regenerated graph contains no `@babel/core`.

Removing the unused lint dependency exposed four production components importing
Zod without declaring it. Seven existing suites failed to load; declare Zod as a
runtime dependency and retain their validation tests. The new lint check also
finds an unused initial `total = 0`; remove only that initialization, retaining
the mandatory assignment before every loop exit.

The generic Jest setup loses matcher declarations in Vitest 5. The package's
Vitest entry point restores method names but still declares the old Assertion
generics, returning HTMLElement instead of void/Promise<void>. A new type/runtime
regression fails under that entry point. Register the public standalone matchers
and augment Vitest's `Matchers<R, T>` interface; both compiler and runtime checks
then pass. No assertion is removed or weakened.

Final local suites: dashboard 1454 tests (79.67% statements), bridge 392 (94.50%)
and app 78 (76.41%). Covered source sets remain 134/16/8 files respectively.
All type checks, dashboard production build, Linux packaged Electron/SQLite
smoke, actionlint and eight workflow pin tests pass. Dashboard audit is clean;
bridge/app retain the documented 3/29 affected package nodes. TypeScript 7 works
for both bridge consumers; the dashboard's parser peer conflict remains open.
