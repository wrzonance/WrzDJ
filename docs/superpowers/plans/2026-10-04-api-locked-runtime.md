# API Locked Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship exactly the locked production Python dependencies and validate real API startup.

**Architecture:** Export hashed requirements using temporary digest-pinned uv and install
artifacts with required hashes and a locked backend for source-only pyaes and ratelimit. Independently export the source lock during an isolated
container smoke test, compare versions, then exercise migrations and HTTP health.

**Tech Stack:** Docker, uv 0.12.23, Python 3.14, Bash, PostgreSQL 16.

**Spec:** docs/superpowers/specs/2026-10-04-api-locked-runtime.md

## Global Constraints

- No pip or uv in runtime; non-root real entrypoint; coverage >=85%.
- Lock hashes required; source builds must use the locked backend without isolation; retain security scans.
- No host ports or live databases; always clean up owned test resources.

## Review Focus

- Architecture-specific wheels: verify arm64 resolution as well as amd64 image build.
- Wrong installed versions: smoke against the old image must fail with drift details.
- Missing distributions and marker exclusions: checker reports missing applicable packages.
- Entrypoint failure: smoke must fail promptly and remove owned resources.
- Stale lock or tampered artifacts: locked export and hash-required installation fail closed.

### Task 1: Lock the API image and validate its runtime

**Files:** Modify server/Dockerfile, server/pyproject.toml, server/uv.lock and .github/workflows/ci.yml; create scripts/test-api-image.sh.

**Interfaces:**
- Consumes: server/pyproject.toml, server/uv.lock, the image's ./scripts/start.sh.
- Produces: `bash scripts/test-api-image.sh IMAGE`, exit 0 only for a matching locked
  graph, no installers, non-root process and successful HTTP /health after migrations.

- [x] Step 1: Write the smoke test. Independently export source requirements without hashes
  from pinned uv offline, evaluate markers and compare installed versions. Use an internal
  Docker network with disposable PostgreSQL and API containers, bounded readiness probes,
  and EXIT cleanup with logs on failure.
- [x] Step 2: Run `bash scripts/test-api-image.sh wrzdj-api:sweep-patched`.
  Expected: exit 1 with actual installed-version mismatches (regression at 3d178561).
- [x] Step 3: Replace floating pip installation with pinned temporary uv mount, locked
  hashed build-group and runtime exports; preinstall locked setuptools, then use
  `uv pip install --system --require-hashes --no-deps --no-build-isolation` for runtime.
  Remove setuptools afterward.
  Remove base pip using its supported uninstall operation. CI loads the built backend
  image as wrzdj-api:smoke and runs the test.
- [x] Step 4: Build wrzdj-api:locked; run smoke, backend lint/format/Bandit/full pytest,
  migration drift, Trivy and arm64 artifact resolution (pyaes/ratelimit use locked source). Expected: all pass, coverage >=85%,
  zero fixable HIGH/CRITICAL vulnerabilities. Exercise a broken-entrypoint fixture and
  confirm failure plus cleanup. Review locked-export and hash enforcement behavior.
- [ ] Step 5: Commit with Conventional Commit and Codex attribution; run task-done with
  `bash scripts/test-api-image.sh wrzdj-api:locked`. Expected: pass. Push draft PR referencing
  #588, verify latest-head technical CI, run exactly one final cross-provider review, fix
  verified findings, then merge using the tested head SHA and recheck finding 129.
