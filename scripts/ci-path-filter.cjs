#!/usr/bin/env node
// Decides which CI jobs a pull request can affect, from its changed files.
//
//   gh api "repos/OWNER/REPO/pulls/N/files" --paginate --jq '.[].filename' \
//     | node scripts/ci-path-filter.cjs >> "$GITHUB_OUTPUT"
//
// Reads one changed path per line on stdin and prints `<job>=true|false` for
// every job in RULES. CI_FILTER_RUN_ALL=true prints true for all of them; the
// workflow sets it for anything that is not a pull request, and when it could
// not list the changed files.
//
// A rule lists what its job READS, not only the directory it tests: a pattern
// ending in `/` matches everything under that directory, any other pattern
// matches that one file. When a job starts reading a new path, add it here; a
// missing entry skips the job on pull requests that change only that path
// (pushes to main still run everything).
'use strict';

// Changing the workflow or this filter re-runs every job.
const RUN_ALL = [
  '.github/workflows/ci.yml',
  'scripts/ci-path-filter.cjs',
  'scripts/ci-path-filter.test.cjs',
];

const NPM_AUDIT_GATE = ['scripts/npm-audit-gate.cjs', '.npm-audit-ignore.json'];

const RULES = {
  // tests/test_workflow_pins.py checks every workflow file.
  backend: ['server/', '.github/workflows/'],
  frontend: [
    'dashboard/',
    'server/openapi.json',
    'scripts/npm-audit-gate.test.cjs',
    'scripts/dependency-health.test.cjs',
    '.github/workflows/dependency-health.yml',
    ...NPM_AUDIT_GATE,
  ],
  bridge: ['bridge/', ...NPM_AUDIT_GATE],
  // Installs and packages the bridge alongside the app.
  bridge_app: [
    'bridge-app/',
    'bridge/',
    'scripts/test-bridge-app-package.cjs',
    'scripts/test-bridge-app-ui.cjs',
    ...NPM_AUDIT_GATE,
  ],
  kiosk: ['kiosk/'],
  docker_build: ['server/', 'dashboard/', 'bridge/', 'deploy/', 'scripts/', 'docker-compose.yml'],
  // The upgrade path depends on the image's schema and packaging, not on
  // request-handling code: docker_build already starts the API on every
  // server/ change.
  postgres_upgrade: [
    'server/Dockerfile',
    'server/.dockerignore',
    'server/pyproject.toml',
    'server/uv.lock',
    'server/alembic.ini',
    'server/alembic/',
    'server/app/models/',
    'deploy/',
    'docker-compose.yml',
    'scripts/test-postgres-upgrade.sh',
    'scripts/test-postgres-upgrade-signals.sh',
  ],
};

function matches(file, pattern) {
  return pattern.endsWith('/') ? file.startsWith(pattern) : file === pattern;
}

function matchesAny(files, patterns) {
  return files.some((file) => patterns.some((pattern) => matches(file, pattern)));
}

/** Returns `{ job: boolean }` for every job in RULES. */
function selectJobs(files, { runAll = false } = {}) {
  const everything = runAll || matchesAny(files, RUN_ALL);
  return Object.fromEntries(
    Object.entries(RULES).map(([job, patterns]) => [job, everything || matchesAny(files, patterns)]),
  );
}

function parseFileList(text) {
  return text.split('\n').map((line) => line.trim()).filter(Boolean);
}

function main() {
  const files = parseFileList(require('node:fs').readFileSync(0, 'utf8'));
  const jobs = selectJobs(files, { runAll: process.env.CI_FILTER_RUN_ALL === 'true' });
  for (const [job, run] of Object.entries(jobs)) {
    process.stdout.write(`${job}=${run}\n`);
  }
}

if (require.main === module) {
  main();
}

module.exports = { RULES, RUN_ALL, parseFileList, selectJobs };
