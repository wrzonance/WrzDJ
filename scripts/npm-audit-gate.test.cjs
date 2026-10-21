'use strict';

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');

const { classifyAuditAdvisories, parseAuditResult, parseIgnores } = require('./npm-audit-gate.cjs');

const TODAY = '2026-10-05';

function advisory(id, severity, name = 'pkg') {
  return {
    source: 1,
    name,
    title: `${name} problem`,
    url: `https://github.com/advisories/${id}`,
    severity,
  };
}

// Shape of `npm audit --json`: a parent package lists the affected child by
// name (a string), and only the child carries the advisory object.
function report(...advisories) {
  const vulnerabilities = { parent: { name: 'parent', severity: 'high', via: ['pkg'] } };
  advisories.forEach((entry, index) => {
    vulnerabilities[`pkg${index}`] = { name: entry.name, severity: entry.severity, via: [entry] };
  });
  return { vulnerabilities };
}

function ignore(id, expires = '2027-01-01', reason = 'not reachable from our code') {
  return { id, expires, reason };
}

test('a high advisory with no ignore blocks', () => {
  const result = classifyAuditAdvisories(report(advisory('GHSA-aaaa', 'high')), [], TODAY);
  assert.deepEqual(result.blocking.map((entry) => entry.id), ['GHSA-aaaa']);
});

test('a critical advisory blocks', () => {
  const result = classifyAuditAdvisories(report(advisory('GHSA-aaaa', 'critical')), [], TODAY);
  assert.equal(result.blocking.length, 1);
});

test('moderate and low advisories do not block', () => {
  const result = classifyAuditAdvisories(
    report(advisory('GHSA-aaaa', 'moderate'), advisory('GHSA-bbbb', 'low')),
    [],
    TODAY,
  );
  assert.deepEqual(result.blocking, []);
});

test('an unexpired ignore suppresses its advisory', () => {
  const result = classifyAuditAdvisories(report(advisory('GHSA-aaaa', 'high')), [ignore('GHSA-aaaa')], TODAY);
  assert.deepEqual(result.blocking, []);
  assert.deepEqual(result.ignored.map((entry) => entry.id), ['GHSA-aaaa']);
});

test('an ignore still applies on its expiry date and stops the day after', () => {
  const audit = report(advisory('GHSA-aaaa', 'high'));
  assert.deepEqual(classifyAuditAdvisories(audit, [ignore('GHSA-aaaa', TODAY)], TODAY).blocking, []);
  const expired = classifyAuditAdvisories(audit, [ignore('GHSA-aaaa', '2026-10-04')], TODAY);
  assert.deepEqual(expired.blocking.map((entry) => entry.id), ['GHSA-aaaa']);
});

test('an ignore for one advisory does not suppress another', () => {
  const result = classifyAuditAdvisories(
    report(advisory('GHSA-aaaa', 'high'), advisory('GHSA-bbbb', 'high')),
    [ignore('GHSA-aaaa')],
    TODAY,
  );
  assert.deepEqual(result.blocking.map((entry) => entry.id), ['GHSA-bbbb']);
});

test('the same advisory reached through two packages is reported once', () => {
  const audit = report(advisory('GHSA-aaaa', 'high'), advisory('GHSA-aaaa', 'high'));
  assert.equal(classifyAuditAdvisories(audit, [], TODAY).blocking.length, 1);
});

test('ignores that match nothing are surfaced as unused', () => {
  const result = classifyAuditAdvisories(report(), [ignore('GHSA-gone')], TODAY);
  assert.deepEqual(result.unused, ['GHSA-gone']);
});

test('a clean report passes', () => {
  assert.deepEqual(classifyAuditAdvisories({ vulnerabilities: {} }, [], TODAY).blocking, []);
});

test('a report without a vulnerabilities map is rejected, not treated as clean', () => {
  assert.throws(() => classifyAuditAdvisories({ error: { code: 'ENOLOCK' } }, [], TODAY), /vulnerabilities/);
});

test('ignore entries need an id, an ISO expiry and a justification', () => {
  assert.throws(() => parseIgnores('[{"id":"GHSA-aaaa","expires":"2027-01-01"}]'), /reason/);
  assert.throws(
    () => parseIgnores('[{"id":"GHSA-aaaa","expires":"next year","reason":"x"}]'),
    /expires/,
  );
  assert.throws(() => parseIgnores('[{"expires":"2027-01-01","reason":"x"}]'), /id/);
  assert.throws(() => parseIgnores('{}'), /array/);
});

test('valid ignore entries parse unchanged', () => {
  const entries = [ignore('GHSA-aaaa')];
  assert.deepEqual(parseIgnores(JSON.stringify(entries)), entries);
});

test('impossible calendar dates are rejected as expiries', () => {
  for (const bad of ['2026-13-01', '2026-02-30', '2025-02-29', '2026-00-10']) {
    assert.throws(() => parseIgnores(JSON.stringify([ignore('GHSA-aaaa', bad)])), /expires/, bad);
  }
  assert.doesNotThrow(() => parseIgnores(JSON.stringify([ignore('GHSA-aaaa', '2028-02-29')])));
});

test('malformed ignore JSON identifies its file and preserves the parse error', () => {
  assert.throws(
    () => parseIgnores('{'),
    (error) => {
      assert.match(error.message, /\.npm-audit-ignore\.json/);
      assert.ok(error.cause instanceof SyntaxError);
      return true;
    },
  );
});

test('null ignore entries fail with an indexed validation error', () => {
  assert.throws(() => parseIgnores('[null]'), /ignore entry 0 must be an object/);
});

// Regression for baseline 57cfcdc6867f: every invalid ignore file identifies its source.
test('ignore schema errors identify the supplied file', () => {
  for (const entries of [{}, [null], [{}], [{ id: 'GHSA-test' }], [ignore('GHSA-test', '2027-01-01', '')]]) {
    assert.throws(
      () => parseIgnores(JSON.stringify(entries), '/tmp/custom-ignores.json'),
      /\/tmp\/custom-ignores\.json/,
    );
  }
});

test('a malformed vulnerability record fails closed instead of passing', () => {
  const malformed = [
    { pkg: { name: 'pkg', severity: 'critical', via: 'dependency' } },
    { pkg: { name: 'pkg', severity: 'critical' } },
    { pkg: { name: 'pkg', severity: 'critical', via: [42] } },
    { pkg: { name: 'pkg', severity: 'critical', via: [{ name: 'pkg', title: 't' }] } },
    { pkg: { name: 'pkg', severity: 'critical', via: [{ severity: 'critical' }] } },
  ];
  for (const vulnerabilities of malformed) {
    assert.throws(() => classifyAuditAdvisories({ vulnerabilities }, [], TODAY), /malformed/);
  }
});

test('an advisory without a url is keyed by its source id', () => {
  const via = { source: 777, name: 'pkg', title: 't', severity: 'high' };
  const result = classifyAuditAdvisories({ vulnerabilities: { pkg: { name: 'pkg', severity: 'high', via: [via] } } }, [], TODAY);
  assert.deepEqual(result.blocking.map((entry) => entry.id), ['777']);
});

const CLEAN = JSON.stringify({ vulnerabilities: {} });

test('npm exit 0 and exit 1 (advisories found) both yield the parsed report', () => {
  assert.deepEqual(parseAuditResult({ status: 0, signal: null, stdout: CLEAN, stderr: '' }), {
    vulnerabilities: {},
  });
  assert.deepEqual(parseAuditResult({ status: 1, signal: null, stdout: CLEAN, stderr: '' }), {
    vulnerabilities: {},
  });
});

test('any other npm exit status or a signal fails closed', () => {
  assert.throws(() => parseAuditResult({ status: 2, signal: null, stdout: CLEAN, stderr: '' }), /exit/);
  assert.throws(() => parseAuditResult({ status: 137, signal: null, stdout: CLEAN, stderr: '' }), /exit/);
  assert.throws(() => parseAuditResult({ status: null, signal: 'SIGKILL', stdout: CLEAN, stderr: '' }), /SIGKILL/);
});

test('a structured npm error fails closed even beside a vulnerabilities map', () => {
  const stdout = JSON.stringify({ error: { code: 'ENOLOCK', summary: 'no lockfile' }, vulnerabilities: {} });
  assert.throws(() => parseAuditResult({ status: 1, signal: null, stdout, stderr: '' }), /ENOLOCK/);
});

test('non-JSON npm output fails closed', () => {
  assert.throws(() => parseAuditResult({ status: 0, signal: null, stdout: 'npm WARN', stderr: '' }), /JSON/);
});

function runGate(t, { auditOutput, auditStatus, ignores = [] }) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'npm-audit-gate-'));
  const scriptsDirectory = path.join(root, 'scripts');
  const binDirectory = path.join(root, 'bin');
  fs.mkdirSync(scriptsDirectory);
  fs.mkdirSync(binDirectory);
  fs.copyFileSync(path.join(__dirname, 'npm-audit-gate.cjs'), path.join(scriptsDirectory, 'npm-audit-gate.cjs'));
  fs.writeFileSync(path.join(root, '.npm-audit-ignore.json'), JSON.stringify(ignores));

  const npmStub = path.join(binDirectory, 'npm');
  fs.writeFileSync(
    npmStub,
    `#!/usr/bin/env node\nrequire('node:assert/strict').deepEqual(process.argv.slice(2), ['audit', '--json']);\nprocess.stdout.write(${JSON.stringify(auditOutput)});\nprocess.exit(${auditStatus});\n`,
    { mode: 0o755 },
  );
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));

  return spawnSync(process.execPath, [path.join(scriptsDirectory, 'npm-audit-gate.cjs')], {
    encoding: 'utf8',
    env: { ...process.env, PATH: `${binDirectory}${path.delimiter}${process.env.PATH}` },
  });
}

test('CLI exits 1 for an unignored blocking advisory', (t) => {
  const result = runGate(t, {
    auditOutput: JSON.stringify(report(advisory('GHSA-aaaa', 'high'))),
    auditStatus: 1,
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /GHSA-aaaa/);
});

test('CLI exits 0 when a blocking advisory has an active explicit ignore', (t) => {
  const result = runGate(t, {
    auditOutput: JSON.stringify(report(advisory('GHSA-aaaa', 'critical'))),
    auditStatus: 1,
    ignores: [ignore('GHSA-aaaa', '2099-12-31')],
  });
  assert.equal(result.status, 0);
  assert.match(result.stdout, /gate passed/);
});

test('CLI exits 2 when npm audit fails operationally', (t) => {
  const result = runGate(t, { auditOutput: '', auditStatus: 2 });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /npm audit exited with status 2/);
});
