'use strict';

const assert = require('node:assert/strict');
const { test } = require('node:test');

const { evaluate, parseIgnores } = require('./npm-audit-gate.cjs');

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
