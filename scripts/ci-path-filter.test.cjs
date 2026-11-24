'use strict';

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');

const { RULES, parseFileList, selectJobs } = require('./ci-path-filter.cjs');

const root = path.join(__dirname, '..');
const script = path.join(__dirname, 'ci-path-filter.cjs');
const workflow = fs.readFileSync(path.join(root, '.github/workflows/ci.yml'), 'utf8');

const trivyWorkflow = fs.readFileSync(path.join(root, '.github/workflows/trivy.yml'), 'utf8');
const selectScript = path.join(__dirname, 'ci-select-jobs.sh');

function selectedIn(group, files, options) {
  const jobs = selectJobs(group, files, options);
  return Object.keys(jobs).filter((job) => jobs[job]).sort();
}

function selected(files, options) {
  return selectedIn('ci', files, options);
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
    assert.ok(selectJobs('ci', [file]).postgres_upgrade, file);
  }
  assert.equal(selectJobs('ci', ['server/app/services/search.py']).postgres_upgrade, false);
});

test('files a job reads from outside its own directory still run it', () => {
  assert.ok(selectJobs('ci', ['server/openapi.json']).frontend);
  assert.ok(selectJobs('ci', ['.npm-audit-ignore.json']).frontend);
  assert.ok(selectJobs('ci', ['.npm-audit-ignore.json']).bridge);
  assert.ok(selectJobs('ci', ['.npm-audit-ignore.json']).bridge_app);
  assert.ok(selectJobs('ci', ['.github/workflows/dependency-health.yml']).frontend);
  // tests/test_workflow_pins.py reads every workflow.
  assert.ok(selectJobs('ci', ['.github/workflows/release.yml']).backend);
});

test('a path pattern does not match a sibling with the same prefix', () => {
  assert.deepEqual(selected(['bridge-app/package.json']), ['bridge_app']);
  assert.deepEqual(selected(['docker-compose.yml.bak']), []);
});

test('documentation-only changes run nothing', () => {
  assert.deepEqual(selected(['README.md', 'docs/RUNBOOK.md', 'AGENTS.md']), []);
});

test('changing the workflow or the filter runs everything', () => {
  const all = Object.keys(RULES.ci).sort();
  assert.deepEqual(selected(['.github/workflows/ci.yml']), all);
  assert.deepEqual(selected(['scripts/ci-path-filter.cjs']), all);
  assert.deepEqual(selected(['README.md'], { runAll: true }), all);
  assert.deepEqual(selected([], { runAll: true }), all);
});

test('the file list tolerates blank lines and CRLF', () => {
  assert.deepEqual(parseFileList('a/b\r\n\n  c/d  \n'), ['a/b', 'c/d']);
});

test('the command prints one output line per job', () => {
  const run = (input, env = {}) => spawnSync(process.execPath, [script, 'ci'], {
    input, encoding: 'utf8', env: { ...process.env, CI_FILTER_RUN_ALL: '', ...env },
  });
  const filtered = run('kiosk/setup.sh\n');
  assert.equal(filtered.status, 0);
  assert.match(filtered.stdout, /^kiosk=true$/m);
  assert.match(filtered.stdout, /^backend=false$/m);
  assert.equal(filtered.stdout.trim().split('\n').length, Object.keys(RULES.ci).length);

  const everything = run('', { CI_FILTER_RUN_ALL: 'true' });
  assert.doesNotMatch(everything.stdout, /=false/);
});

// A job added to ci.yml without a rule, an output or a gate entry would either
// always run or, worse, be skipped or ignored silently.
test('every filtered job is wired into the workflow', () => {
  for (const job of Object.keys(RULES.ci)) {
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

test('an image is scanned when its build context changes', () => {
  assert.deepEqual(selectedIn('trivy', ['server/app/main.py']), ['api']);
  assert.deepEqual(selectedIn('trivy', ['dashboard/package-lock.json']), ['web']);
  assert.deepEqual(selectedIn('trivy', ['deploy/dev-proxy/Dockerfile', 'bridge/Dockerfile']), ['bridge', 'proxy']);
  assert.deepEqual(selectedIn('trivy', ['deploy/deploy.sh', 'README.md']), []);
});

test('the ignore list and the scan workflow rescan every image', () => {
  const all = Object.keys(RULES.trivy).sort();
  assert.deepEqual(selectedIn('trivy', ['.trivyignore']), all);
  assert.deepEqual(selectedIn('trivy', ['.github/workflows/trivy.yml']), all);
  assert.deepEqual(selectedIn('trivy', ['scripts/ci-select-jobs.sh']), all);
  // ci.yml is not an input of the scans, nor trivy.yml of the CI jobs.
  assert.deepEqual(selectedIn('trivy', ['.github/workflows/ci.yml']), []);
  assert.ok(!selected(['.trivyignore']).includes('frontend'));
});

test('an unknown group is an error, not an empty selection', () => {
  assert.throws(() => selectJobs('nope', []), /unknown job group/);
  const run = spawnSync(process.execPath, [script, 'nope'], { input: '', encoding: 'utf8' });
  assert.equal(run.status, 2);
  assert.equal(run.stdout, '');
});

// An image in the matrix without a rule would never be scanned on a pull request.
test('every image trivy.yml can scan has a rule', () => {
  const images = [...trivyWorkflow.matchAll(/\{"image": "([a-z-]+)", "context": "\.\/([^"]+)"/g)];
  assert.deepEqual(images.map((match) => match[1]).sort(), Object.keys(RULES.trivy).sort());
  for (const [, image, context] of images) {
    assert.deepEqual(RULES.trivy[image], [`${context}/`], `${image} is not selected by its build context`);
  }
});

function runSelect(group, { event, ghScript }) {
  const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'wrzdj-select-'));
  try {
    fs.writeFileSync(path.join(scratch, 'gh'), `#!/bin/sh\n${ghScript}\n`, { mode: 0o755 });
    return spawnSync('bash', [selectScript, group], {
      encoding: 'utf8',
      env: {
        ...process.env,
        PATH: `${scratch}${path.delimiter}${process.env.PATH}`,
        CI_FILTER_RUN_ALL: '',
        EVENT_NAME: event,
        GITHUB_REPOSITORY: 'owner/repo',
        PR_NUMBER: '7',
      },
    });
  } finally {
    fs.rmSync(scratch, { recursive: true, force: true });
  }
}

test('a pull request is filtered by the files the API lists', () => {
  const run = runSelect('ci', { event: 'pull_request', ghScript: 'echo kiosk/setup.sh' });
  assert.equal(run.status, 0, run.stderr);
  assert.match(run.stdout, /^kiosk=true$/m);
  assert.match(run.stdout, /^backend=false$/m);
});

test('everything runs when the event is not a pull request', () => {
  const run = runSelect('ci', { event: 'push', ghScript: 'echo "gh must not be called" >&2; exit 1' });
  assert.equal(run.status, 0, run.stderr);
  assert.doesNotMatch(run.stdout, /=false/);
  assert.doesNotMatch(run.stderr, /gh must not be called/);
});

test('everything runs when the changed files cannot be listed', () => {
  const run = runSelect('trivy', { event: 'pull_request', ghScript: 'echo kiosk/setup.sh; exit 1' });
  assert.equal(run.status, 0, run.stderr);
  assert.doesNotMatch(run.stdout, /=false/);
});

test('everything runs when the file list reaches the API limit', () => {
  const run = runSelect('ci', { event: 'pull_request', ghScript: 'seq -f "docs/%g.md" 3000' });
  assert.equal(run.status, 0, run.stderr);
  assert.doesNotMatch(run.stdout, /=false/);
});

test('a broken filter fails the selection instead of selecting nothing', () => {
  const run = runSelect('nope', { event: 'pull_request', ghScript: 'echo kiosk/setup.sh' });
  assert.notEqual(run.status, 0);
  assert.equal(run.stdout, '');
});
