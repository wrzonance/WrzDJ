# Low-impact refactor candidate evaluation

This evaluates the six candidate topics in issue #507 against the
`feat/issue-507` tree, which is stacked on #506. Candidate 5 contains three
separate constants/page-size observations. The original handoff was validated
on 2026-06-19; several findings were already resolved by the current base.

## Decisions

| Candidate | Decision | Evidence and rationale |
|---|---|---|
| Kiosk pairing nonce cache | Follow-up #713 | The process-local cache matches today's single-worker startup, so cross-worker storage is conditional. However, in the current deployment two kiosks sharing one IP can overwrite each other's challenges, and a missing or incorrect nonce consumes the outstanding challenge. Issue #713 tracks preserving independent, IP-bound, single-use challenges; use shared storage if deployment moves to multiple workers. |
| LLM recommendation rate limit cache | Defer | The rate remains admin-tunable in the database and the route refreshes the local cache after SlowAPI evaluates it. This leaves one request on the old value after a setting change and different workers could diverge. Current startup is single-worker, so a shared cache/TTL is not justified yet. Revisit with multi-worker deployment or a request to make admin changes take effect immediately. |
| Bridge retry/backoff duplication | No further extraction | `bridge/src/bridge.ts` and `bridge-app/src/main/bridge-runner.ts` both import the shared `bridge/src/http-retry.ts` helpers/constants and shared `CircuitBreaker` through the `@bridge/*` alias. Their `postWithRetry` wrappers still own different lifecycle and authentication behavior. Extracting those wrappers would add abstraction around the remaining legitimate differences. |
| Setbuilder reorder/document math | Already resolved in current base | `reorderMath.ts` owns both `buildMovedIds` and `buildReorderedIds`; `documentMath.ts` owns `insertPoolTrackIntoDocument` and `lockSlotsInDocument`. Tests import the pure helpers from those modules. No additional change is needed. |
| Magic numbers | Select only CSV follow-up #711 | **210-second fallback:** the value appears in the backend deterministic builder and two frontend modules (`types.ts` and `poolRuntime.ts`). Sharing one value across Python and TypeScript would require generation or API wiring, not warranted for a stable fallback. **CSV caps:** `events_exports.py` bounds both exports to 10,000 rows, but normal CSV responses do not indicate truncation; #711 tracks an explicit signal and DJ-facing handling. **Public page size:** join and collect use `PAGE_SIZE = 100`; kiosk display starts at 100. These are UI fetch/growth sizes, while backend `DEFAULT_PAGE_SIZE` applies only when a query omits `limit`. Reusing a frontend constant would not align backend defaults, so defer the small cleanup. |
| Pydantic mutable list defaults | Already resolved in current base | `schemas/user.py` and all list fields in `schemas/recommendation.py` use `Field(default_factory=list)`. No behavior or style change remains. |

## Follow-up boundary

Selected follow-ups are kiosk challenge handling (#713) and visible CSV export
truncation (#711). The LLM cache's shared-store need remains conditional on
multi-worker deployment. The other items are already resolved or too small to
justify abstraction in this pass.

## Validation

This is an evaluation-only change. No application behavior or tests changed.
Evidence was checked in the current worktree at the paths named above and in
`server/scripts/start.sh`.

🤖 Prepared by Codex gpt-6-luna.
