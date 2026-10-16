// Regression for workflow output interpolation in 5384cef9 (#794).
// Execute the actual reporting scripts; only the external GitHub CLI is stubbed.
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const { createRequire } = require('node:module');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');

const dashboardRequire = createRequire(path.join(__dirname, '../dashboard/package.json'));
const yaml = dashboardRequire('js-yaml');
const workflow = yaml.load(fs.readFileSync(
  path.join(__dirname, '../.github/workflows/dependency-health.yml'), 'utf8',
));

for (const stepName of ['Report contract test drift', 'Report new upstream releases']) {
  test(`${stepName} treats upstream output as data, not shell code`, () => {
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'wrzdj-workflow-'));
    try {
      const marker = path.join(scratch, 'executed');
      const calls = path.join(scratch, 'calls.jsonl');
      const payload = `$(touch '${marker}')`;
      const values = {
        'needs.contract-tests-latest.outputs.stagelinq_version': payload,
        'needs.contract-tests-latest.outputs.alphatheta_version': '1.2.3',
        'needs.upstream-monitor.outputs.stagelinq_latest': payload,
        'needs.upstream-monitor.outputs.alphatheta_latest': '1.2.3',
        'needs.upstream-monitor.outputs.stagelinq_pinned': '1.0.0',
        'needs.upstream-monitor.outputs.alphatheta_pinned': '1.2.3',
        'github.server_url': 'https://github.com',
        'github.repository': 'owner/repo',
        'github.run_id': '123',
      };
      const expand = (value) => value.replace(/\$\{\{\s*(.*?)\s*\}\}/g, (_, key) => {
        assert.ok(Object.hasOwn(values, key), `Missing workflow fixture: ${key}`);
        return values[key];
      });
      fs.writeFileSync(path.join(scratch, 'gh'), `#!${process.execPath}
const fs = require('node:fs');
const args = process.argv.slice(2);
if (args[0] !== 'issue') process.exit(2);
if (args[1] === 'list') process.stdout.write('0');
else if (args[1] === 'create') fs.appendFileSync(process.env.CALLS, JSON.stringify(args) + '\\n');
else process.exit(2);
`, { mode: 0o755 });
      const step = workflow.jobs['create-issues'].steps.find((item) => item.name === stepName);
      assert.ok(step, `Workflow step exists: ${stepName}`);
      const result = spawnSync('bash', ['--noprofile', '--norc', '-e', '-o', 'pipefail', '-c', expand(step.run)], {
        env: {
          ...process.env,
          ...Object.fromEntries(Object.entries(step.env || {}).map(([key, value]) => [key, expand(value)])),
          PATH: `${scratch}${path.delimiter}${process.env.PATH}`,
          CALLS: calls,
        },
        encoding: 'utf8',
        timeout: 5000,
      });
      assert.equal(result.status, 0, result.stderr);
      assert.equal(fs.existsSync(marker), false, 'upstream output executed as shell code');
      assert.ok(fs.existsSync(calls), 'report must create an issue');
      const requests = fs.readFileSync(calls, 'utf8').trim().split('\n').map(JSON.parse);
      assert.equal(requests.length, 1);
      const body = requests[0][requests[0].indexOf('--body') + 1];
      assert.ok(body.includes(payload), 'issue body must preserve the literal upstream version');
    } finally {
      fs.rmSync(scratch, { recursive: true, force: true });
    }
  });
}

for (const version of ['1.2.3', '1.2.3\nforged=true']) {
  test(`Capture installed versions validates package metadata: ${JSON.stringify(version)}`, () => {
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'wrzdj-versions-'));
    try {
      for (const pkg of ['stagelinq', 'alphatheta-connect']) {
        const directory = path.join(scratch, 'node_modules', pkg);
        fs.mkdirSync(directory, { recursive: true });
        fs.writeFileSync(path.join(directory, 'package.json'), JSON.stringify({ version }));
      }
      const output = path.join(scratch, 'outputs');
      const step = workflow.jobs['contract-tests-latest'].steps.find((item) => item.id === 'versions');
      assert.ok(step, 'Capture installed versions step exists');
      const result = spawnSync('bash', ['--noprofile', '--norc', '-e', '-o', 'pipefail', '-c', step.run], {
        cwd: scratch,
        env: { ...process.env, GITHUB_OUTPUT: output },
        encoding: 'utf8',
        timeout: 5000,
      });
      if (version.includes('\n')) {
        assert.notEqual(result.status, 0, 'malformed version must fail the capture step');
        assert.equal(fs.existsSync(output), false, 'malformed version must not write output keys');
      } else {
        assert.equal(result.status, 0, result.stderr);
        assert.equal(fs.readFileSync(output, 'utf8'), 'stagelinq=1.2.3\nalphatheta=1.2.3\n');
      }
    } finally {
      fs.rmSync(scratch, { recursive: true, force: true });
    }
  });
}
