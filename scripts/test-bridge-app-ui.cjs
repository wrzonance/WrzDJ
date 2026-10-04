// Regression for the Forge 8 migration from 9046d6eb: a packaged app must load
// its preload, expose IPC, and persist settings across actual Electron launches.
// Usage: node scripts/test-bridge-app-ui.cjs PACKAGED_ELECTRON_EXECUTABLE
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { createRequire } = require('node:module');
const os = require('node:os');
const path = require('node:path');

const appRequire = createRequire(path.join(__dirname, '../bridge-app/package.json'));
const { _electron: electron } = appRequire('playwright-core');

async function checkLaunch(executablePath, profile, update) {
  const application = await electron.launch({
    executablePath,
    args: ['--no-sandbox', '--disable-gpu', `--user-data-dir=${profile}`],
    timeout: 20_000,
  });
  const timeout = setTimeout(() => {
    console.error('Packaged UI check exceeded 30 seconds');
    application.process().kill('SIGKILL');
  }, 30_000);
  try {
    assert.equal(await application.evaluate(({ app }) => app.getPath('userData')), profile);
    const page = await application.firstWindow({ timeout: 10_000 });
    await application.evaluate(({ BrowserWindow }) => {
      for (const window of BrowserWindow.getAllWindows()) window.hide();
    });
    await page.waitForURL((url) => url.protocol === 'file:', { timeout: 5_000 });
    await page.waitForFunction(() => typeof window.bridgeApi?.getSettings === 'function',
      null, { timeout: 5_000 });
    const result = await page.evaluate(async (write) => {
      const api = window.bridgeApi;
      if (write) {
        await api.updateSettings({ liveThresholdSeconds: 37 });
        // Wrong types must still be filtered at the IPC boundary.
        await api.updateSettings({ liveThresholdSeconds: 'invalid' });
      }
      return {
        threshold: (await api.getSettings()).liveThresholdSeconds,
        authenticated: (await api.getAuthState()).isAuthenticated,
      };
    }, update);
    assert.deepEqual(result, { threshold: 37, authenticated: false });
  } finally {
    clearTimeout(timeout);
    const deadline = setTimeout(() => application.process().kill('SIGKILL'), 5_000);
    try { await application.close(); }
    finally { clearTimeout(deadline); }
  }
}

async function main() {
  assert.equal(process.argv.length, 3, 'Pass the packaged Electron executable');
  const executable = path.resolve(process.argv[2]);
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'wrzdj-package-ui-'));
  try {
    await checkLaunch(executable, profile, true);
    await checkLaunch(executable, profile, false);
    console.log('Packaged renderer, preload IPC and settings persistence smoke passed');
  } finally {
    fs.rmSync(profile, { recursive: true, force: true });
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
