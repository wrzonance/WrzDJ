#!/usr/bin/env node
'use strict';

// Blocking `npm audit` gate for ci.yml. Run it from a package directory:
//
//   node ../scripts/npm-audit-gate.cjs
//
// A high or critical advisory fails the job unless .npm-audit-ignore.json at the
// repo root lists it with a justification and an expiry date. `npm audit` has no
// per-advisory ignore of its own, so without this the only choices were "never
// block" or "never green" while an upstream had no patched release.

const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const BLOCKING_SEVERITIES = new Set(['high', 'critical']);
const IGNORE_FILE = path.join(__dirname, '..', '.npm-audit-ignore.json');
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function parseIgnores(raw) {
  const entries = JSON.parse(raw);
  if (!Array.isArray(entries)) {
    throw new Error('npm audit ignore file must be a JSON array');
  }
  entries.forEach((entry, index) => {
    if (typeof entry.id !== 'string' || entry.id === '') {
      throw new Error(`ignore entry ${index} needs an advisory id`);
    }
    if (typeof entry.expires !== 'string' || !ISO_DATE.test(entry.expires)) {
      throw new Error(`ignore entry ${entry.id} needs expires as YYYY-MM-DD`);
    }
    if (typeof entry.reason !== 'string' || entry.reason.trim() === '') {
      throw new Error(`ignore entry ${entry.id} needs a reason`);
    }
  });
  return entries;
}

// A package's `via` lists either an advisory object or the name of the
// dependency it inherits one from; only the objects are advisories.
function collectAdvisories(report) {
  if (!report || typeof report.vulnerabilities !== 'object' || report.vulnerabilities === null) {
    throw new Error('npm audit output has no vulnerabilities map; refusing to treat it as clean');
  }
  const byId = new Map();
  for (const vulnerability of Object.values(report.vulnerabilities)) {
    for (const via of vulnerability.via ?? []) {
      if (typeof via === 'string') continue;
      const id = via.url ? via.url.split('/').pop() : String(via.source);
      if (!byId.has(id)) {
        byId.set(id, { id, severity: via.severity, package: via.name, title: via.title });
      }
    }
  }
  return [...byId.values()];
}

function evaluate(report, ignores, today) {
  const advisories = collectAdvisories(report).filter((entry) =>
    BLOCKING_SEVERITIES.has(entry.severity),
  );
  // ISO dates compare correctly as strings; an entry is valid through its expiry date.
  const active = new Set(ignores.filter((entry) => entry.expires >= today).map((entry) => entry.id));
  const present = new Set(advisories.map((entry) => entry.id));
  return {
    blocking: advisories.filter((entry) => !active.has(entry.id)),
    ignored: advisories.filter((entry) => active.has(entry.id)),
    unused: ignores.filter((entry) => !present.has(entry.id)).map((entry) => entry.id),
  };
}

function runNpmAudit() {
  // npm exits non-zero whenever it finds anything, so the JSON is the result.
  const result = spawnSync('npm', ['audit', '--json'], {
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });
  if (result.error) {
    throw new Error(`could not run npm audit: ${result.error.message}`);
  }
  try {
    return JSON.parse(result.stdout);
  } catch (error) {
    throw new Error(`npm audit did not return JSON: ${error.message}\n${result.stderr}`);
  }
}

function describe(entry) {
  return `  ${entry.id}  ${entry.severity}  ${entry.package}: ${entry.title}`;
}

function main() {
  const ignores = parseIgnores(fs.readFileSync(IGNORE_FILE, 'utf8'));
  const today = new Date().toISOString().slice(0, 10);
  const { blocking, ignored, unused } = evaluate(runNpmAudit(), ignores, today);

  if (ignored.length > 0) {
    console.log(`Ignored by ${path.basename(IGNORE_FILE)}:\n${ignored.map(describe).join('\n')}`);
  }
  if (unused.length > 0) {
    // One ignore file serves every package, so an entry unused here may be live elsewhere.
    console.log(`Ignore entries not matched in this package: ${unused.join(', ')}`);
  }
  if (blocking.length > 0) {
    console.error(
      `npm audit: ${blocking.length} high/critical advisory(ies) not covered by an unexpired ignore:\n` +
        blocking.map(describe).join('\n'),
    );
    process.exit(1);
  }
  console.log('npm audit gate passed: no unignored high/critical advisories.');
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(`npm audit gate failed: ${error.message}`);
    process.exit(2);
  }
}

module.exports = { collectAdvisories, evaluate, parseIgnores };
