# Container Image Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh the queued bridge, database and development proxy images with verified runtime compatibility.
**Architecture:** Refresh image references, separate bridge build/runtime stages and build a patched development proxy. Preserve service contracts; reuse #721, subsume #722 and close #733.
**Tech Stack:** Docker, Node 26/TypeScript, PostgreSQL 16, nginx 1.31.
**Spec:** docs/superpowers/specs/2026-10-04-container-image-updates.md

## Global Constraints

Use the exact verified index digests from the spec; preserve volume paths and
service ports. PostgreSQL 18 remains queued. Exclude Joe's #714/#713.

## Review Focus

- Native SQLite ABI/musl: run real queries through the protocol packages.
- Existing database: create a sentinel on the previous image, restart on the new one and query it.
- ORM/schema compatibility: run Alembic upgrade and drift check on an isolated database.
- Proxy behavior: render actual templates; test TLS proxying, redirects, overlay and API headers.
- Reproducibility: compare all Compose structures apart from image references; scan changed images.

## Task 1: Refresh image references

Files: `bridge/Dockerfile`, `scripts/test-bridge-image.sh`,
`scripts/test-proxy-image.sh`, `.github/workflows/{ci,trivy}.yml`,
`deploy/dev-proxy/{Dockerfile,setup.sh}`, `docker-compose.yml`,
`deploy/docker-compose.yml`, `deploy/docker-compose.ghcr.yml`,
`deploy/dev-proxy/docker-compose.yml`.

- [x] Read current PR bodies/diffs/feedback, confirm authors and registry digests.
- [x] Build baseline bridge and exercise its native SQLite dependency.
- [x] Merge #721's bot head into the main-based branch; apply #722's digest and nginx's queued version.
- [x] Build bridge, run protocol/native smoke, types, coverage and audit.
- [x] Test old/new PostgreSQL persistence and application migration/drift checks.
- [x] Test nginx templates/routing/headers and compare Compose structures.
- [x] Reproduce #733: old bridge runtime retains npm; old proxy scan has two fixable HIGH packages.
- [x] Separate bridge stages/prune tools, patch proxy OS packages, and add CI smoke/scan coverage; new images pass probes and fixable HIGH/CRITICAL scans.
- [ ] Run container scans, commit and push to #721; update its scope and validation body.
- [ ] Verify latest-head CI, perform one final cross-provider review, resolve findings and revalidate.
- [ ] Merge the exact tested SHA, verify main, close #722 only with supersession evidence and refresh inventory.

No application data structures or interfaces change. Image contracts now exclude
build tools and preserve protocol/native functionality. The initial probes
exposed #733; its regression was observed RED then GREEN. The proxy image scan
likewise changed from two fixable HIGH findings to zero. PostgreSQL migration
and persistence passed; gosu-only findings have a source-based disposition in
the spec. Tests exercise runtime behavior, not duplicated version literals.
