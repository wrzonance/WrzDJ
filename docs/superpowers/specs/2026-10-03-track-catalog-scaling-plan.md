# Global Track Catalog: Scaling Plan

**Issue:** #546 · **Date:** 2026-10-03
**Related:** [Master Song Store design](2026-06-23-master-track-store-design.md) · #539 / #540
**Status:** Recommended operating plan; thresholds are initial guardrails, to be checked against a measured baseline.

## Decision

“Global” means shared by every DJ, event, and setbuilder **inside one WrzDJ deployment**. The `tracks` table remains in that deployment's PostgreSQL database. We do not operate a cross-deployment catalog today. If multiple WrzDJ deployments need the same canonical catalog, the target is a dedicated enrichment service that owns the catalog and exposes an API; sharing database credentials or directly connecting multiple applications to one table is not the target architecture.

Do not move infrastructure because of row count alone. The master-store design's ISRC and signature lookups use unique B-tree indexes, and the catalog is append-mostly. Keep it on the primary PostgreSQL instance while measured catalog operations meet the guardrails below. The row and disk figures in the Capacity plan section are planning estimates from #546, not measured production data or latency promises.

## Metrics and measurement

Start collecting a 30-day baseline before making a scaling move. Report catalog-specific values separately from the rest of the application database:

| Signal | How to measure | Initial action threshold |
|---|---|---|
| Track lookup latency | p99 database execution time for ISRC/signature lookup and end-to-end resolver p99, measured with application query spans or histograms | Investigate when DB-side p99 exceeds 25 ms, or end-to-end p99 exceeds 100 ms, for 7 days. These are review thresholds, not user-facing SLOs. |
| Primary database pressure | Host CPU and I/O wait; database read/write latency; database connection use; application pool acquisition p95 | Start mitigation review when CPU stays above 70%, I/O wait above 10%, connections above 70% of the configured limit, or pool acquisition p95 exceeds 100 ms for 15 minutes on 3 days in a week. Confirm catalog work contributes before moving it. |
| Request-path impact | p95/p99 latency and DB pool wait for request submission and event operations, compared with the prior 30-day baseline | Escalate if p99 regresses by 25% or more for 7 days and query/host evidence links the regression to catalog work. |
| Catalog footprint | `pg_total_relation_size('tracks')`, row count, growth rate, and `pg_stat_user_tables` dead tuples / vacuum / analyze history | Review capacity at 10M rows or 7 GB; plan the next capacity test at 100M rows or 70 GB. Size alone does not trigger a split. |
| Cache value (when enabled) | Hit rate, miss latency, invalidation count, stale-read rate, memory use | Keep a cache only if representative load tests show at least 50% lookup hit rate and a meaningful reduction in primary read load without stale metadata regressions. |

Use PostgreSQL's `pg_stat_statements` for aggregate statement execution statistics, application query spans or histograms for p99, and relation-size functions for on-disk size. Track autovacuum/analyze activity because PostgreSQL derives maintenance triggers from table size and configurable thresholds; tune the `tracks` table only if observed maintenance lag or bloat warrants it. Do not infer hot-table pressure from row count alone.

## Staged response

1. **Single PostgreSQL instance (current).** Keep the existing unique B-tree lookups and default autovacuum behavior. Record the metrics above. At one million rows, continue on the current instance if the measured latency and contention guardrails remain healthy.
2. **Tune and reduce read load.** First inspect query plans and indexes. Add `pg_trgm` with a GIN index only when a real normalized-title/artist fuzzy-search query exists and an `EXPLAIN (ANALYZE, BUFFERS)` benchmark demonstrates a benefit; `dedupe_sig` is a hash and cannot support fuzzy matching. If lookups are read-heavy, try a bounded per-process cache with a short TTL and write-through invalidation after `upsert_track`; measure hit rate and stale-read behavior. Add Redis only if multiple API processes need a shared cache and the measured benefit justifies operating it. Tune per-table autovacuum/analyze thresholds only from observed churn and maintenance lag.
3. **Read replica or separate database.** Use a read replica when read traffic is the demonstrated source of primary contention and the lookup path can tolerate replication lag. Move `tracks` to a separate PostgreSQL instance when catalog writes, vacuum, or storage continue to harm the transactional request/event workload after cheaper measures, or when measured growth means the current database volume cannot maintain the 30% free-space reserve or meet a documented backup/restore objective. This is an application data-boundary change, not a transparent connection-string change; complete the prerequisites in the next section first.
4. **Dedicated enrichment service.** Extract ownership when cross-deployment sharing is a product requirement, or when independent scaling/deployment is needed after the database split. The service owns identity resolution, provenance precedence, enrichment scheduling, and storage; callers use an authenticated, versioned API. Do not introduce sharding before measured single-database limits require it.

For workload-driven moves, require the relevant threshold to hold for its stated window, evidence that catalog activity contributes, and measurement of or a reason to rule out the lower-cost stage. Product or operational triggers follow their own evidence: cross-deployment sharing requires an explicit product requirement, while storage isolation requires a documented capacity or backup/restore objective. Neither requires a catalog-attributed latency regression. Recheck workload thresholds after the first 30 days of telemetry and after each infrastructure stage.

## Data-boundary costs of a separate database

The current ORM schema has no foreign key from `Request` or `SetPoolTrack` to `Track`: `Request.track_id` is not present, and `SetPoolTrack.track_id` is a namespaced string. However, the master-store design proposes local nullable foreign keys for both tables. Such foreign keys and SQL joins cannot cross PostgreSQL instances, so that part of the design must be revised before a split. Keep request and pool membership data in the application database, use an opaque catalog identifier or ISRC/signature in the service contract, and replace any future cross-table joins with bounded batch API reads.

The current `get_track` and `upsert_track` functions take the application's SQLAlchemy `Session`. A separate instance needs a catalog client/storage boundary instead. It also removes shared transaction semantics: request enrichment currently commits request data before the best-effort catalog upsert; REST pool imports use similar commit-first behavior, while agent pool edits can currently include the catalog flush in their transaction and undo. Before extraction, define durable retry/idempotency for catalog writes, acceptable partial failure and stale-read behavior, and how agent undo interacts with a separately committed catalog. Plan and rehearse an export/backfill, consistency check, cutover, and rollback path. Do not advertise the move as transparent until these contracts are implemented.

## Capacity plan

Use these estimates from issue #546 as an initial envelope for the current row shape (typed nullable enrichment columns plus provenance and indexes). The estimate should be replaced with `pg_total_relation_size` from representative production data before purchasing capacity.

| Catalog rows | Estimated table + indexes | Capacity action |
|---:|---:|---|
| 1M | Under 1 GB | No move by default; confirm metrics and backup capacity. |
| 10M | 6–7 GB | Run a representative lookup/upsert benchmark with a warm and cold cache. Ensure the database volume has at least 30% free space after catalog, application tables, WAL, and migration headroom. |
| 100M | 60–70 GB | Capacity-test a primary sized for at least 100 GB of catalog headroom, then add application data, WAL, backups, and operational reserve. Prefer a separate database only if the contention or isolation triggers above apply. |

PostgreSQL caches active pages rather than requiring the whole catalog to fit in RAM. Benchmark with the expected working set and available memory; do not size RAM by multiplying row count by row width. Before either capacity milestone, measure actual heap/index size, growth, cache hit behavior, and backup/restore time.

## Implementation boundaries

- No schema, request-flow, or infrastructure behavior changes in this planning issue.
- Keep `get_track` and `upsert_track` as the storage boundary; application callers should not depend on replica/cache/database topology.
- A future fuzzy-matching change must have its own query contract and benchmark. A future cache must define key normalization, TTL, invalidation, and acceptable staleness before implementation.
- A cross-deployment catalog decision requires an explicit product requirement, tenant/privacy review, service ownership/on-call plan, and migration/availability design.

## References

- PostgreSQL [`pg_stat_statements`](https://www.postgresql.org/docs/current/pgstatstatements.html) reports statement planning and execution statistics.
- PostgreSQL [routine vacuuming](https://www.postgresql.org/docs/current/routine-vacuuming.html) and [vacuum configuration](https://www.postgresql.org/docs/current/runtime-config-vacuum.html) document autovacuum thresholds and per-table storage settings.
- PostgreSQL [`EXPLAIN`](https://www.postgresql.org/docs/current/using-explain.html) documents plan inspection and the limits of reported execution time.
