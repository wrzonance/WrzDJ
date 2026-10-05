'use strict';

const assert = require('node:assert/strict');
const { test } = require('node:test');

const { evaluate, parseAuditResult, parseIgnores } = require('./npm-audit-gate.cjs');

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
  const result = evaluate(report(advisory('GHSA-aaaa', 'high')), [], TODAY);
  assert.deepEqual(result.blocking.map((entry) => entry.id), ['GHSA-aaaa']);
});

test('a critical advisory blocks', () => {
  const result = evaluate(report(advisory('GHSA-aaaa', 'critical')), [], TODAY);
  assert.equal(result.blocking.length, 1);
});

test('moderate and low advisories do not block', () => {
  const result = evaluate(
    report(advisory('GHSA-aaaa', 'moderate'), advisory('GHSA-bbbb', 'low')),
    [],
    TODAY,
  );
  assert.deepEqual(result.blocking, []);
});

test('an unexpired ignore suppresses its advisory', () => {
  const result = evaluate(report(advisory('GHSA-aaaa', 'high')), [ignore('GHSA-aaaa')], TODAY);
  assert.deepEqual(result.blocking, []);
  assert.deepEqual(result.ignored.map((entry) => entry.id), ['GHSA-aaaa']);
});

test('an ignore still applies on its expiry date and stops the day after', () => {
  const audit = report(advisory('GHSA-aaaa', 'high'));
  assert.deepEqual(evaluate(audit, [ignore('GHSA-aaaa', TODAY)], TODAY).blocking, []);
  const expired = evaluate(audit, [ignore('GHSA-aaaa', '2026-10-04')], TODAY);
  assert.deepEqual(expired.blocking.map((entry) => entry.id), ['GHSA-aaaa']);
});

test('an ignore for one advisory does not suppress another', () => {
  const result = evaluate(
    report(advisory('GHSA-aaaa', 'high'), advisory('GHSA-bbbb', 'high')),
    [ignore('GHSA-aaaa')],
    TODAY,
  );
  assert.deepEqual(result.blocking.map((entry) => entry.id), ['GHSA-bbbb']);
});

test('the same advisory reached through two packages is reported once', () => {
  const audit = report(advisory('GHSA-aaaa', 'high'), advisory('GHSA-aaaa', 'high'));
  assert.equal(evaluate(audit, [], TODAY).blocking.length, 1);
});

test('ignores that match nothing are surfaced as unused', () => {
  const result = evaluate(report(), [ignore('GHSA-gone')], TODAY);
  assert.deepEqual(result.unused, ['GHSA-gone']);
});

test('a clean report passes', () => {
  assert.deepEqual(evaluate({ vulnerabilities: {} }, [], TODAY).blocking, []);
});

test('a report without a vulnerabilities map is rejected, not treated as clean', () => {
  assert.throws(() => evaluate({ error: { code: 'ENOLOCK' } }, [], TODAY), /vulnerabilities/);
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

test('a malformed vulnerability record fails closed instead of passing', () => {
  const malformed = [
    { pkg: { name: 'pkg', severity: 'critical', via: 'dependency' } },
    { pkg: { name: 'pkg', severity: 'critical' } },
    { pkg: { name: 'pkg', severity: 'critical', via: [42] } },
    { pkg: { name: 'pkg', severity: 'critical', via: [{ name: 'pkg', title: 't' }] } },
    { pkg: { name: 'pkg', severity: 'critical', via: [{ severity: 'critical' }] } },
  ];
  for (const vulnerabilities of malformed) {
    assert.throws(() => evaluate({ vulnerabilities }, [], TODAY), /malformed/);
  }
});

test('an advisory without a url is keyed by its source id', () => {
  const via = { source: 777, name: 'pkg', title: 't', severity: 'high' };
  const result = evaluate({ vulnerabilities: { pkg: { name: 'pkg', severity: 'high', via: [via] } } }, [], TODAY);
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
