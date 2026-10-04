# JavaScript toolchain plan

1. **Shapes/interfaces:** retain application APIs and all active lint/test gates.
   Tool contracts are published engine/peer ranges, Vitest matcher types and the
   TypeScript CLI. No application data model changes are planned.
2. **Change map:** three manifests/locks; dashboard ESLint/setup config; Node
   workflow versions and prerequisite docs. Test/source edits only for observed
   compatibility failures, with red/green regression evidence.
3. **Disposable spike:** reproduce TypeScript 7/parser incompatibility separately;
   capture the 60-rule effective lint baseline and sole Babel consumer before
   removing unused plugin packages. No spike code ships.
4. **Invariants:** all baseline active rules remain; test counts and coverage
   source sets stay intact; thresholds/scanners stay enabled; registry graphs
   remain valid; production build and Electron native smoke still succeed.
5. **Implementation/validation:** regenerate locks with npm, install cleanly and
   run the existing suites as migration regressions. Diagnose failures before
   modifying behavior. Keep unsupported combinations documented and unresolved.
6. **Integration:** update existing draft PR #680, verify latest-head CI, perform
   one final adversarial review, fix verified findings, merge with SHA matching,
   verify main, record supersession and refresh all queues.
