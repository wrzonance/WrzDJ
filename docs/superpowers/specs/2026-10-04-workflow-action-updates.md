# Workflow action dependency updates

Tracked by dependency dashboard #588; reuse Renovate PR #728.
Base: `e677067e6984c6a062d930549bb24f2ffa46576f`.

Update the pinned CodeQL, Docker build/publish and release actions to the current
queued versions. Keep workflow triggers, permissions, inputs, runner selections,
release platforms and scanner/test gates intact. This includes the build/push
action's upstream fix for workflow-command injection through metadata logs.

Verified official version tags resolve to these commits:

| Action | Version | Commit |
| --- | --- | --- |
| github/codeql-action | 4.38.2 | `2892aa5e19bbd11bc0cff5427e3b750a04d9e3c2` |
| docker/build-push-action | 7.4.0 | `c3c9e263c25d99ce0380d002d59b67737d91b0dc` |
| docker/setup-buildx-action | 4.4.1 | `f87e5991a6d7451dcb8d9637bfbc97413f497069` |
| docker/setup-qemu-action | 4.4.0 | `99012661954931238ded8c8b007157a8430204e1` |
| softprops/action-gh-release | 3.0.3 | `efb35369e0ad2afab669f228072c1b0d510eae64` |

All 17 call sites use inputs supported by the target manifests. Comparing eight
unique action manifests found no removed inputs or changed defaults/required
flags. The release action moves from Node 20 to Node 24; these GitHub-hosted
runners already execute the other actions on Node 24. Its release-only behavior
is checked against the manifest and upstream release notes; no release is
published merely to test an action update.

Invariants: every changed reference uses the verified 40-character commit;
workflow structure is identical after removing action references; existing pin
tests and actionlint pass. PR CI must exercise CodeQL, both container scans and
Docker smoke checks. Main must additionally pass Scorecard and image publishing.

Sources: official release notes and manifests at each pinned commit:
https://github.com/github/codeql-action/releases/tag/v4.38.2
https://github.com/docker/build-push-action/releases/tag/v7.4.0
https://github.com/docker/setup-buildx-action/releases/tag/v4.4.1
https://github.com/docker/setup-qemu-action/releases/tag/v4.4.0
https://github.com/softprops/action-gh-release/releases/tag/v3.0.3
