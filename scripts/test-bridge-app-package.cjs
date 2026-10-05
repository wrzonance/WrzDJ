// Regression #723 at a3aa51ae: successful packaging must produce Electron-compatible natives.
// Usage: node scripts/test-bridge-app-package.cjs ELECTRON_EXECUTABLE RESOURCES_DIRECTORY
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const { createRequire } = require('node:module');
const path = require('node:path');

if (process.argv[2] !== '--electron') {
  assert.equal(process.argv.length, 4, 'Pass the packaged executable and resources directory');
  const result = spawnSync(path.resolve(process.argv[2]), [
    __filename, '--electron', path.resolve(process.argv[3]),
  ], {
    env: { ...process.env, ELECTRON_RUN_AS_NODE: '1' },
    stdio: 'inherit',
    timeout: 30_000,
  });
  if (result.error) throw result.error;
  assert.equal(result.status, 0, `Packaged runtime failed (signal: ${result.signal})`);
} else {
  assert.ok(process.versions.electron, 'Smoke test must run in the packaged Electron runtime');
  // Regression at 9046d6eb: Node resolves real paths when an extraction directory
  // is reached through a symlink. Compare canonical paths for package confinement.
  const appRoot = fs.realpathSync(path.join(process.argv[3], 'app.asar'));
  const manifest = JSON.parse(fs.readFileSync(path.join(appRoot, 'package.json'), 'utf8'));
  assert.ok(fs.statSync(path.join(appRoot, manifest.main)).isFile(), 'Packaged main entry is missing');
  const appRequire = createRequire(path.join(appRoot, manifest.main));
  const expected = JSON.parse(fs.readFileSync(
    path.join(__dirname, '../bridge-app/package.json'), 'utf8',
  )).dependencies;

  function packagedEntry(name) {
    const entry = appRequire.resolve(name);
    assert.ok(entry.startsWith(`${appRoot}${path.sep}`), `${name} resolved outside the package`);
    return entry;
  }

  for (const name of ['alphatheta-connect', 'stagelinq', 'metadata-connect', 'onelibrary-connect']) {
    let directory = path.dirname(packagedEntry(name));
    let version;
    while (directory.startsWith(`${appRoot}${path.sep}`)) {
      const filename = path.join(directory, 'package.json');
      if (fs.existsSync(filename)) {
        const pkg = JSON.parse(fs.readFileSync(filename, 'utf8'));
        if (pkg.name === name) { version = pkg.version; break; }
      }
      directory = path.dirname(directory);
    }
    assert.equal(version, expected[name], `${name} differs from the declared production pin`);
    appRequire(name);
  }

  const { StageLinq } = appRequire('stagelinq');
  const messages = [];
  const write = (...args) => messages.push(args.join(' '));
  const levels = ['trace', 'debug', 'info', 'warn', 'error'];
  StageLinq.options = {
    downloadDbSources: false,
    enableFileTranfer: true,
    logger: Object.fromEntries(levels.map((level) => [level, write])),
  };
  for (const level of levels) {
    StageLinq.logger[level](`package-smoke-${level}`, 42);
    assert.ok(messages.includes(`package-smoke-${level} 42`));
  }
  assert.equal(typeof appRequire('alphatheta-connect').bringOnline, 'function');

  for (const name of ['alphatheta-connect', 'stagelinq', 'onelibrary-connect']) {
    const libraryRequire = createRequire(packagedEntry(name));
    assert.ok(libraryRequire.resolve('better-sqlite3-multiple-ciphers').startsWith(`${appRoot}${path.sep}`));
    const Database = libraryRequire('better-sqlite3-multiple-ciphers');
    const db = new Database(':memory:');
    try { assert.deepEqual(db.prepare('SELECT 42 AS value').get(), { value: 42 }); }
    finally { db.close(); }
  }
  console.log(`Packaged protocol and SQLite smoke passed (Electron ${process.versions.electron}, ABI ${process.versions.modules})`);
  // The upstream device singleton starts a timer even without connect(). No sockets were opened.
  process.exit(0);
}
