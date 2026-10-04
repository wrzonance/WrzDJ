# Workflow action update plan

1. Structures/interfaces: existing workflow jobs, action inputs and outputs stay
   intact. Compare target manifests and defaults with the currently pinned
   manifests; verify version tags including annotated-tag dereferencing.
2. Change map: `ci.yml`, `codeql.yml`, `docker-publish.yml`, `release.yml`,
   `scorecard.yml` and `trivy.yml`. Adopt bot #728's CodeQL pin updates and update
   Docker/release pins in the same dependency group.
3. Spike/revert: the bot head merges cleanly into the verified base. Abort that
   trial merge; retain the read-only manifest/input comparison evidence.
4. Invariants: preserve the entire parsed workflow structure except verified
   action references. Use the existing pin regression and actionlint rather than
   adding a test which merely repeats the selected version numbers.
5. Implement the pin substitutions and validate all workflows locally. Reuse #728
   as a draft, push, and verify all technical CI on the exact head.
6. Run the single final cross-provider review, fix verified findings without a
   second review, and merge the tested SHA. Verify main and refresh all queues.
