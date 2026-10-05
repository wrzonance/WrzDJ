#!/usr/bin/env bash
# Regression #733 at 7d4fd401: the runtime shipped vulnerable build tooling.
set -euo pipefail
image=${1:?Usage: test-bridge-image.sh IMAGE}
root=$(cd "$(dirname "$0")/.." && pwd)

docker run --rm --network none --entrypoint sh "$image" -ec '
  for tool in npm npx tsc vitest; do
    if command -v "$tool" >/dev/null; then
      echo "Build tool remains in runtime: $tool" >&2
      exit 1
    fi
  done
'
docker run --rm --interactive --network none --entrypoint node \
  --volume "$root/bridge/package.json:/tmp/expected-package.json:ro" "$image" <<'JS'
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const app = createRequire('/app/package.json');
const expected = JSON.parse(fs.readFileSync('/tmp/expected-package.json', 'utf8'));
assert.ok(fs.statSync('/app/dist/index.js').isFile());
for (const name of ['typescript', 'vitest', 'tsx']) {
  assert.throws(() => app.resolve(`${name}/package.json`), { code: 'MODULE_NOT_FOUND' },
    `Development dependency remains in runtime: ${name}`);
}
for (const [name, version] of Object.entries(expected.dependencies)) {
  let directory = path.dirname(app.resolve(name));
  let manifest;
  while (directory.startsWith('/app/node_modules/')) {
    const filename = path.join(directory, 'package.json');
    if (fs.existsSync(filename)) {
      const candidate = JSON.parse(fs.readFileSync(filename, 'utf8'));
      if (candidate.name === name) { manifest = candidate; break; }
    }
    directory = path.dirname(directory);
  }
  assert.equal(manifest?.version, version, `${name} differs from production pin`);
  app(name);
}
for (const name of ['alphatheta-connect', 'stagelinq', 'onelibrary-connect']) {
  const library = createRequire(app.resolve(name));
  const Database = library('better-sqlite3-multiple-ciphers');
  const db = new Database(':memory:');
  try { assert.deepEqual(db.prepare('SELECT 42 AS value').get(), { value: 42 }); }
  finally { db.close(); }
}
console.log(`Bridge protocols/native SQLite passed without build tools (${process.version}, ABI ${process.versions.modules})`);
// The upstream StageLinq singleton starts a timer even without discovery.
process.exit(0);
JS
