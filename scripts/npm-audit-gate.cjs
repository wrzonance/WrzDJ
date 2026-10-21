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
const SEVERITIES = new Set(['info', 'low', 'moderate', 'high', 'critical']);

/**
 * @typedef {'info' | 'low' | 'moderate' | 'high' | 'critical'} AuditSeverity
 * @typedef {{ id: string, expires: string, reason: string }} AuditIgnoreEntry
 * @typedef {{ id: string, severity: AuditSeverity, package?: string, title?: string }} AuditAdvisory
 * @typedef {{ severity: AuditSeverity, source?: string | number, url?: string,
 *   name?: string, title?: string }} NpmAuditVia
 * @typedef {{ error?: { code?: string, summary?: string },
 *   vulnerabilities?: Record<string, { via: Array<string | NpmAuditVia> }> }} NpmAuditReport
 * @typedef {{ blocking: AuditAdvisory[], ignored: AuditAdvisory[], unused: string[] }} AuditClassification
 * @typedef {{ status: number | null, signal: string | null, stdout: string,
 *   stderr: string }} AuditProcessResult
 */

// A string that both matches the ISO shape and survives a round trip through
// Date is a real calendar day; "2026-13-01" or "2026-02-30" would be normalized.
/** @param {string} value */
function isCalendarDate(value) {
  if (!ISO_DATE.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

/**
 * Parse and validate the repository's advisory ignore entries.
 * @param {string} raw Raw JSON from the ignore file.
 * @param {string} [fileName] Name reported for parse or validation failures.
 * @returns {AuditIgnoreEntry[]} Validated ignores; expiry remains inclusive.
 */
function parseIgnores(raw, fileName = path.basename(IGNORE_FILE)) {
  let entries;
  try {
    entries = JSON.parse(raw);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`could not parse ${fileName}: ${detail}`, { cause: error });
  }
  if (!Array.isArray(entries)) {
    throw new Error(`${fileName}: npm audit ignore file must be a JSON array`);
  }
  entries.forEach((entry, index) => {
    if (typeof entry !== 'object' || entry === null || Array.isArray(entry)) {
      throw new Error(`${fileName}: ignore entry ${index} must be an object`);
    }
    if (typeof entry.id !== 'string' || entry.id === '') {
      throw new Error(`${fileName}: ignore entry ${index} needs an advisory id`);
    }
    if (typeof entry.expires !== 'string' || !isCalendarDate(entry.expires)) {
      throw new Error(`${fileName}: ignore entry ${entry.id} needs expires as a real YYYY-MM-DD date`);
    }
    if (typeof entry.reason !== 'string' || entry.reason.trim() === '') {
      throw new Error(`${fileName}: ignore entry ${entry.id} needs a reason`);
    }
  });
  return entries;
}

/** @param {string} name @param {string} what */
function malformedAuditRecordError(name, what) {
  return new Error(
    `npm audit record for ${name} is malformed (${what}); refusing to treat it as clean`,
  );
}

// A package's `via` lists either an advisory object or the name of the
// dependency it inherits one from; only the objects are advisories. Anything
// that is neither is a shape this gate does not understand, so it fails closed.
/** @param {string} name @param {string | NpmAuditVia} via @returns {AuditAdvisory | null} */
function advisoryFrom(name, via) {
  if (typeof via === 'string') return null;
  if (typeof via !== 'object' || via === null) {
    throw malformedAuditRecordError(name, 'via entry is not a string or object');
  }
  if (!SEVERITIES.has(via.severity)) {
    throw malformedAuditRecordError(name, 'advisory has no known severity');
  }
  const id = typeof via.url === 'string' && via.url !== '' ? via.url.split('/').pop() : via.source;
  if (id === undefined || id === null || id === '') {
    throw malformedAuditRecordError(name, 'advisory has no url or source id');
  }
  return { id: String(id), severity: via.severity, package: via.name, title: via.title };
}

/**
 * Extract unique advisories from npm's vulnerability records.
 * @param {NpmAuditReport} report Parsed npm audit report.
 * @returns {AuditAdvisory[]} Advisories deduplicated by advisory id.
 */
function collectAdvisories(report) {
  if (!report || typeof report.vulnerabilities !== 'object' || report.vulnerabilities === null) {
    throw new Error('npm audit output has no vulnerabilities map; refusing to treat it as clean');
  }
  const byId = new Map();
  for (const [name, vulnerability] of Object.entries(report.vulnerabilities)) {
    if (!Array.isArray(vulnerability?.via)) throw malformedAuditRecordError(name, 'via is not an array');
    for (const via of vulnerability.via) {
      const advisory = advisoryFrom(name, via);
      if (advisory && !byId.has(advisory.id)) byId.set(advisory.id, advisory);
    }
  }
  return [...byId.values()];
}

/**
 * Separate blocking advisories, active ignores, and ignores not present in this report.
 * @param {NpmAuditReport} report Parsed npm audit report.
 * @param {AuditIgnoreEntry[]} ignores Validated repository ignores.
 * @param {string} today Current date as an ISO YYYY-MM-DD value.
 * @returns {AuditClassification} Blocking, ignored, and unused advisory entries.
 */
function classifyAuditAdvisories(report, ignores, today) {
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

// npm audit exits 0 when clean and 1 when it found advisories; the JSON on
// stdout is the result either way. Any other outcome means the audit did not
// actually run, and a gate must not pass on a report it never received.
/**
 * Validate npm's process outcome and parse its JSON report.
 * @param {AuditProcessResult} result Captured npm audit process result.
 * @returns {NpmAuditReport} Parsed JSON audit report.
 */
function parseAuditResult({ status, signal, stdout, stderr }) {
  if (signal) throw new Error(`npm audit was killed by ${signal}`);
  if (status !== 0 && status !== 1) {
    throw new Error(`npm audit exited with status ${status}\n${stderr}`);
  }
  let report;
  try {
    report = JSON.parse(stdout);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`npm audit did not return JSON: ${detail}\n${stderr}`, { cause: error });
  }
  if (report && typeof report === 'object' && report.error) {
    const { code, summary } = report.error;
    throw new Error(`npm audit reported an error: ${code ?? ''} ${summary ?? ''}`.trim());
  }
  return report;
}

function runNpmAudit() {
  const result = spawnSync('npm', ['audit', '--json'], {
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });
  if (result.error) {
    throw new Error(`could not run npm audit: ${result.error.message}`, { cause: result.error });
  }
  return parseAuditResult(result);
}

/** @param {AuditAdvisory} entry */
function formatAdvisory(entry) {
  return `  ${entry.id}  ${entry.severity}  ${entry.package}: ${entry.title}`;
}

function main() {
  const ignores = parseIgnores(fs.readFileSync(IGNORE_FILE, 'utf8'));
  const today = new Date().toISOString().slice(0, 10);
  const { blocking, ignored, unused } = classifyAuditAdvisories(runNpmAudit(), ignores, today);

  if (ignored.length > 0) {
    console.log(`Ignored by ${path.basename(IGNORE_FILE)}:\n${ignored.map(formatAdvisory).join('\n')}`);
  }
  if (unused.length > 0) {
    // One ignore file serves every package, so an entry unused here may be live elsewhere.
    console.log(`Ignore entries not matched in this package: ${unused.join(', ')}`);
  }
  if (blocking.length > 0) {
    console.error(
      `npm audit: ${blocking.length} high/critical advisory(ies) not covered by an unexpired ignore:\n` +
        blocking.map(formatAdvisory).join('\n'),
    );
    process.exit(1);
  }
  console.log('npm audit gate passed: no unignored high/critical advisories.');
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    console.error(`npm audit gate failed: ${detail}`);
    process.exit(2);
  }
}

module.exports = { collectAdvisories, classifyAuditAdvisories, parseAuditResult, parseIgnores };
