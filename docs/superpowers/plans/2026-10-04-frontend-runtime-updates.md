# Frontend runtime update plan

1. Structs/interfaces: retain WrzDJ's identify payload and guest state; use the
   library's public ThumbmarkResponse instead of its legacy hash/data adapter.
2. Change map: dashboard manifest/lock, guest identity hook, corresponding mocks
   and a real-library network regression. No backend schema or identity change.
3. Spike: intercepted browser sampling probe confirms upstream telemetry;
   isolated js-yaml 5 and Redocly 2 installs prove both incompatibilities. Keep
   probes outside the repository; no forced overrides survive them.
4. Invariants/TDD: first reproduce external requests through the current hook;
   disable both telemetry paths per call, preserving hash/component payloads.
   Test initial identification and refresh with the actual library. Existing
   tests retain cached identity, returning guests and error behavior.
5. Update the three runtime dependencies with npm; verify clean install, complete
   dependency graph, npm audit, lint, TypeScript, full tests/coverage, production
   build, canonical OpenAPI generation, and actual browser fingerprint behavior.
6. Reuse bot #726 as a draft, link #730 and #588, push and verify latest-head CI.
   Perform the single final cross-provider review; fix verified findings without
   repeating it. Merge the tested SHA, verify main, close superseded #729 with
   evidence, and refresh the dashboard and all finding queues.
