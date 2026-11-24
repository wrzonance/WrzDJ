#!/usr/bin/env node
// Decides which jobs of a workflow a pull request can affect, from its changed
// files. scripts/ci-select-jobs.sh is the entry point the workflows call.
//
//   node scripts/ci-path-filter.cjs GROUP < changed-files.txt
//
// Reads one changed path per line on stdin and prints `<job>=true|false` for
// every job in RULES[GROUP]. CI_FILTER_RUN_ALL=true prints true for all of them.
//
// A rule lists what its job READS, not only the directory it tests: a pattern
// ending in `/` matches everything under that directory, any other pattern
// matches that one file. When a job starts reading a new path, add it here; a
// missing entry skips the job on pull requests that change only that path
// (pushes to main still run everything).
'use strict';

// Changing a workflow, or this filter, re-runs every job of that workflow.
const FILTER = [
  'scripts/ci-path-filter.cjs',
  'scripts/ci-path-filter.test.cjs',
  'scripts/ci-select-jobs.sh',
];
const RUN_ALL = {
  ci: ['.github/workflows/ci.yml', ...FILTER],
  // .trivyignore decides which findings fail any of the scans.
  trivy: ['.github/workflows/trivy.yml', '.trivyignore', ...FILTER],
};

const NPM_AUDIT_GATE = ['scripts/npm-audit-gate.cjs', '.npm-audit-ignore.json'];

const RULES = {
  // One entry per ci.yml job.
  ci: {
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
  },
  // One entry per image trivy.yml scans: its build context.
  trivy: {
    api: ['server/'],
    web: ['dashboard/'],
    bridge: ['bridge/'],
    proxy: ['deploy/dev-proxy/'],
  },
};

function matches(file, pattern) {
  return pattern.endsWith('/') ? file.startsWith(pattern) : file === pattern;
}

function matchesAny(files, patterns) {
  return files.some((file) => patterns.some((pattern) => matches(file, pattern)));
}

/** Returns `{ job: boolean }` for every job in RULES[group]. */
function selectJobs(group, files, { runAll = false } = {}) {
  if (!Object.hasOwn(RULES, group)) {
    throw new Error(`unknown job group "${group}"; expected one of: ${Object.keys(RULES).join(', ')}`);
  }
  const everything = runAll || matchesAny(files, RUN_ALL[group]);
  return Object.fromEntries(
    Object.entries(RULES[group]).map(([job, patterns]) => [job, everything || matchesAny(files, patterns)]),
  );
}

function parseFileList(text) {
  return text.split('\n').map((line) => line.trim()).filter(Boolean);
}

function main() {
  const files = parseFileList(require('node:fs').readFileSync(0, 'utf8'));
  const jobs = selectJobs(process.argv[2], files, { runAll: process.env.CI_FILTER_RUN_ALL === 'true' });
  for (const [job, run] of Object.entries(jobs)) {
    process.stdout.write(`${job}=${run}\n`);
  }
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    process.stderr.write(`ci-path-filter: ${error.message}\n`);
    process.exit(2);
  }
}

module.exports = { RULES, RUN_ALL, parseFileList, selectJobs };
