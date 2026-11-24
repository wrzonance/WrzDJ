'use strict';

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');

const { RULES, parseFileList, selectJobs } = require('./ci-path-filter.cjs');

const root = path.join(__dirname, '..');
const script = path.join(__dirname, 'ci-path-filter.cjs');
const workflow = fs.readFileSync(path.join(root, '.github/workflows/ci.yml'), 'utf8');

function selected(files, options) {
  const jobs = selectJobs(files, options);
  return Object.keys(jobs).filter((job) => jobs[job]).sort();
}

test('a change runs only the jobs that read it', () => {
  assert.deepEqual(selected(['kiosk/wifi-portal/portal.py']), ['kiosk']);
  assert.deepEqual(selected(['dashboard/app/page.tsx']), ['docker_build', 'frontend']);
  assert.deepEqual(selected(['server/app/api/requests.py']), ['backend', 'docker_build']);
  assert.deepEqual(selected(['bridge-app/src/main.ts']), ['bridge_app']);
  assert.deepEqual(selected(['bridge/src/index.ts']), ['bridge', 'bridge_app', 'docker_build']);
});

test('schema, packaging and deploy changes run the PostgreSQL upgrade test', () => {
  for (const file of [
    'server/alembic/versions/070_example.py',
    'server/app/models/event.py',
    'server/Dockerfile',
    'server/uv.lock',
    'deploy/scripts/upgrade-postgres-volume.sh',
    'docker-compose.yml',
  ]) {
    assert.ok(selectJobs([file]).postgres_upgrade, file);
  }
  assert.equal(selectJobs(['server/app/services/search.py']).postgres_upgrade, false);
});

test('files a job reads from outside its own directory still run it', () => {
  assert.ok(selectJobs(['server/openapi.json']).frontend);
  assert.ok(selectJobs(['.npm-audit-ignore.json']).frontend);
  assert.ok(selectJobs(['.npm-audit-ignore.json']).bridge);
  assert.ok(selectJobs(['.npm-audit-ignore.json']).bridge_app);
  assert.ok(selectJobs(['.github/workflows/dependency-health.yml']).frontend);
  // tests/test_workflow_pins.py reads every workflow.
  assert.ok(selectJobs(['.github/workflows/release.yml']).backend);
});

test('a path pattern does not match a sibling with the same prefix', () => {
  assert.deepEqual(selected(['bridge-app/package.json']), ['bridge_app']);
  assert.deepEqual(selected(['docker-compose.yml.bak']), []);
});

test('documentation-only changes run nothing', () => {
  assert.deepEqual(selected(['README.md', 'docs/RUNBOOK.md', 'AGENTS.md']), []);
});

test('changing the workflow or the filter runs everything', () => {
  const all = Object.keys(RULES).sort();
  assert.deepEqual(selected(['.github/workflows/ci.yml']), all);
  assert.deepEqual(selected(['scripts/ci-path-filter.cjs']), all);
  assert.deepEqual(selected(['README.md'], { runAll: true }), all);
  assert.deepEqual(selected([], { runAll: true }), all);
});

test('the file list tolerates blank lines and CRLF', () => {
  assert.deepEqual(parseFileList('a/b\r\n\n  c/d  \n'), ['a/b', 'c/d']);
});

test('the command prints one output line per job', () => {
  const run = (input, env = {}) => spawnSync(process.execPath, [script], {
    input, encoding: 'utf8', env: { ...process.env, CI_FILTER_RUN_ALL: '', ...env },
  });
  const filtered = run('kiosk/setup.sh\n');
  assert.equal(filtered.status, 0);
  assert.match(filtered.stdout, /^kiosk=true$/m);
  assert.match(filtered.stdout, /^backend=false$/m);
  assert.equal(filtered.stdout.trim().split('\n').length, Object.keys(RULES).length);

  const everything = run('', { CI_FILTER_RUN_ALL: 'true' });
  assert.doesNotMatch(everything.stdout, /=false/);
});

// A job added to ci.yml without a rule, an output or a gate entry would either
// always run or, worse, be skipped or ignored silently.
test('every filtered job is wired into the workflow', () => {
  for (const job of Object.keys(RULES)) {
    assert.match(workflow, new RegExp(`^      ${job}: \\$\\{\\{ steps\\.filter\\.outputs\\.${job} \\}\\}$`, 'm'),
      `changes job does not export ${job}`);
    assert.match(workflow, new RegExp(`^    if: needs\\.changes\\.outputs\\.${job} == 'true'$`, 'm'),
      `no job is conditional on ${job}`);
  }
});

test('the gate waits for every other job', () => {
  const jobs = workflow.slice(workflow.indexOf('\njobs:\n'));
  const jobIds = [...jobs.matchAll(/^  ([a-z][a-z0-9-]*):$/gm)].map((match) => match[1]);
  const gate = workflow.slice(workflow.indexOf('\n  gate:'));
  const needs = gate.match(/needs: \[([^\]]+)\]/)[1].split(',').map((id) => id.trim()).sort();
  assert.deepEqual(needs, jobIds.filter((id) => id !== 'gate').sort());
});
