# Low-impact refactor candidate evaluation

This evaluates the six candidates in issue #507 against the `feat/issue-507`
tree, which is stacked on #506. The original handoff was validated on
2026-06-19; several findings were already resolved by the current base.

## Decisions

| Candidate | Decision | Evidence and rationale |
|---|---|---|
| Kiosk pairing nonce cache | Defer | `server/scripts/start.sh` launches one Uvicorn process without `--workers`, matching the cache's documented assumption. The per-IP key can make two kiosks behind one NAT replace each other's challenge, and a failed attempt consumes the cached nonce, but pairing is manual and the impact is bounded. Revisit before multi-worker deployment or if multi-kiosk pairing becomes a supported scenario. |
| LLM recommendation rate limit cache | Defer | The rate remains admin-tunable in the database and the route refreshes the local cache after SlowAPI evaluates it. This leaves one request on the old value after a setting change and different workers could diverge. Current startup is single-worker, so a shared cache/TTL is not justified yet. Revisit with multi-worker deployment or a request to make admin changes take effect immediately. |
| Bridge retry/backoff duplication | No further extraction | `bridge/src/bridge.ts` and `bridge-app/src/main/bridge-runner.ts` both import the shared `bridge/src/http-retry.ts` helpers/constants and shared `CircuitBreaker` through the `@bridge/*` alias. Their `postWithRetry` wrappers still own different lifecycle and authentication behavior. Extracting those wrappers would add abstraction around the remaining legitimate differences. |
| Setbuilder reorder/document math | Already resolved in current base | `reorderMath.ts` owns both `buildMovedIds` and `buildReorderedIds`; `documentMath.ts` owns `insertPoolTrackIntoDocument` and `lockSlotsInDocument`. Tests import the pure helpers from those modules. No additional change is needed. |
| 210-second track fallback | Defer | The backend and frontend use the same value, but it appears in the backend deterministic builder and two frontend modules (`types.ts` and `poolRuntime.ts`). A single source shared across Python and TypeScript would require new generation or API wiring, which is not warranted for a stable fallback. Keep the matching values documented and revisit if either side changes. |
| 10,000-row CSV export caps | Follow-up #711 | `events_exports.py` bounds both exports to 10,000 rows to protect memory and response time, but the endpoints return a normal CSV without indicating that the result was truncated. This is a real, bounded risk for large events. Issue #711 tracks an explicit truncation signal and DJ-facing handling separately before changing endpoint behavior. |
| Public list initial page size | Defer | Join and collect use `PAGE_SIZE = 100`; the kiosk display starts at 100. These are UI fetch/growth sizes, while backend `DEFAULT_PAGE_SIZE` is only a fallback for omitted query parameters. Reusing a frontend constant could reduce repetition, but it does not align or change backend defaults. Low payoff. |
| Pydantic mutable list defaults | Already resolved in current base | `schemas/user.py` and all list fields in `schemas/recommendation.py` use `Field(default_factory=list)`. No behavior or style change remains. |

## Follow-up boundary

The only selected follow-up is the potentially truncated CSV export, now tracked
in #711. That issue defines a response signal and dashboard handling before implementation. The
two multi-worker concerns remain conditional on a deployment change; the other
items are already resolved or too small to justify abstraction in this pass.

## Validation

This is an evaluation-only change. No application behavior or tests changed.
Evidence was checked in the current worktree at the paths named above and in
`server/scripts/start.sh`.

🤖 Prepared by Codex gpt-6-luna.
