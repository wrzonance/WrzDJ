import { afterEach, describe, expect, it } from 'vitest';
import { ok } from 'node:assert/strict';
import { loadConfigFromFile, type Plugin } from 'vite';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { stageBridgeDependencies } from '../../../packaging/stage-bridge-dependencies';

const appRoot = path.resolve(__dirname, '../../../');
const bridgeRoot = fs.realpathSync(path.join(appRoot, '../bridge'));
const outputDirs: string[] = [];

afterEach(() => {
  for (const directory of outputDirs.splice(0)) {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

describe('Vite external dependency staging', () => {
  // Regression for the clean-install packaging failure at 57cfcdc6867f.
  it('stages the bridge-owned protocol dependency tree for Forge', async () => {
    const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'wrzdj-package-stage-'));
    outputDirs.push(outputDir);

    const loaded = await loadConfigFromFile(
      { command: 'build', mode: 'production' },
      path.join(appRoot, 'vite.main.config.ts'),
      appRoot,
      'silent',
    );
    ok(loaded, 'the production Vite config should load');
    const stagingPlugin = loaded.config.plugins?.find((option) => {
      if (!option || Array.isArray(option) || typeof option !== 'object') return false;
      return 'name' in option && option.name === 'copy-externals';
    }) as Plugin | undefined;
    ok(stagingPlugin, 'the bridge dependency staging plugin should be configured');
    const writeBundle = stagingPlugin.writeBundle;
    const writeBundleHandler = typeof writeBundle === 'function' ? writeBundle : writeBundle?.handler;
    if (writeBundleHandler) {
      await Reflect.apply(writeBundleHandler, {}, [{ dir: outputDir }, {}]);
    }

    const ownerManifest = JSON.parse(
      fs.readFileSync(path.join(bridgeRoot, 'package.json'), 'utf8'),
    ) as { dependencies: Record<string, string> };
    const ownerRequire = createRequire(path.join(bridgeRoot, 'package.json'));
    const stagedRequire = createRequire(path.join(outputDir, 'package.json'));

    for (const name of ['alphatheta-connect', 'stagelinq']) {
      const entry = stagedRequire.resolve(name);
      expect(entry.startsWith(path.join(outputDir, 'node_modules') + path.sep)).toBe(true);
      expect(ownerRequire.resolve(name)).toBeDefined();
    }

    for (const name of ['alphatheta-connect', 'stagelinq', 'metadata-connect', 'onelibrary-connect']) {
      const entry = stagedRequire.resolve(name);
      let directory = path.dirname(entry);
      let version: string | undefined;
      while (directory.startsWith(path.join(outputDir, 'node_modules') + path.sep)) {
        const manifestPath = path.join(directory, 'package.json');
        if (fs.existsSync(manifestPath)) {
          const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8')) as {
            name?: string;
            version?: string;
          };
          if (manifest.name === name) {
            version = manifest.version;
            break;
          }
        }
        directory = path.dirname(directory);
      }
      expect(version, `${name} must be staged at its bridge-pinned version`)
        .toBe(ownerManifest.dependencies[name]);
      expect(() => stagedRequire(name)).not.toThrow();
    }

    for (const name of ['alphatheta-connect', 'onelibrary-connect']) {
      const sourceProtocolEntry = ownerRequire.resolve(name);
      const stagedProtocolEntry = stagedRequire.resolve(name);
      const sourceNativeEntry = createRequire(sourceProtocolEntry)
        .resolve('better-sqlite3-multiple-ciphers');
      const stagedNativeEntry = createRequire(stagedProtocolEntry)
        .resolve('better-sqlite3-multiple-ciphers');
      expect(stagedNativeEntry.startsWith(path.join(outputDir, 'node_modules') + path.sep)).toBe(true);
      expect(packageVersion(sourceNativeEntry)).toBe(packageVersion(stagedNativeEntry));
    }
  });

  it('fails with the missing package and bridge owner when a required external is absent', () => {
    const fixtureRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'wrzdj-package-owner-'));
    outputDirs.push(fixtureRoot);
    const manifestPath = path.join(fixtureRoot, 'package.json');
    fs.writeFileSync(manifestPath, JSON.stringify({
      name: '@wrzdj/bridge',
      dependencies: { 'missing-protocol': '1.2.3' },
    }));

    expect(() => stageBridgeDependencies(
      manifestPath,
      path.join(fixtureRoot, 'build'),
      ['missing-protocol'],
    )).toThrow(/Cannot stage required package "missing-protocol" from .*@wrzdj\/bridge/);
  });

  it('preserves shared dependency identity across owners', () => {
    const fixtureRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'wrzdj-package-shared-'));
    outputDirs.push(fixtureRoot);
    const fixture = createDependencyFixture(fixtureRoot, false);
    const sourceOwnerA = createRequire(path.join(fixture.ownerA, 'index.js'));
    const sourceOwnerB = createRequire(path.join(fixture.ownerB, 'index.js'));
    const sourceSharedA = sourceOwnerA.resolve('shared-lib');
    const sourceSharedB = sourceOwnerB.resolve('shared-lib');
    expect(sourceSharedA).toBe(sourceSharedB);
    expect(sourceOwnerA('shared-lib')).toBe(sourceOwnerB('shared-lib'));

    stageBridgeDependencies(fixture.manifestPath, fixture.outputDirectory, []);

    const stagedOwnerA = createRequire(path.join(fixture.outputDirectory, 'node_modules/owner-a/index.js'));
    const stagedOwnerB = createRequire(path.join(fixture.outputDirectory, 'node_modules/owner-b/index.js'));
    expect(stagedOwnerA.resolve('shared-lib')).toBe(stagedOwnerB.resolve('shared-lib'));
    expect(stagedOwnerA('shared-lib')).toBe(stagedOwnerB('shared-lib'));
  });

  it('keeps conflicting dependency versions nested under their owners', () => {
    const fixtureRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'wrzdj-package-conflicts-'));
    outputDirs.push(fixtureRoot);
    const fixture = createDependencyFixture(fixtureRoot, true);
    const sourceOwnerA = createRequire(path.join(fixture.ownerA, 'index.js'));
    const sourceOwnerB = createRequire(path.join(fixture.ownerB, 'index.js'));
    const sourceSharedA = sourceOwnerA.resolve('shared-lib');
    const sourceSharedB = sourceOwnerB.resolve('shared-lib');
    expect(sourceSharedA).not.toBe(sourceSharedB);
    expect(packageVersion(sourceSharedA)).toBe('1.0.0');
    expect(packageVersion(sourceSharedB)).toBe('2.0.0');

    stageBridgeDependencies(fixture.manifestPath, fixture.outputDirectory, []);

    const stagedOwnerA = createRequire(path.join(fixture.outputDirectory, 'node_modules/owner-a/index.js'));
    const stagedOwnerB = createRequire(path.join(fixture.outputDirectory, 'node_modules/owner-b/index.js'));
    const stagedSharedA = stagedOwnerA.resolve('shared-lib');
    const stagedSharedB = stagedOwnerB.resolve('shared-lib');
    expect(stagedSharedA).not.toBe(stagedSharedB);
    expect(packageVersion(stagedSharedA)).toBe('1.0.0');
    expect(packageVersion(stagedSharedB)).toBe('2.0.0');
  });
});

function packageVersion(entryPath: string): string {
  let directory = path.dirname(entryPath);
  while (directory !== path.dirname(directory)) {
    const manifestPath = path.join(directory, 'package.json');
    if (fs.existsSync(manifestPath)) {
      const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8')) as {
        version?: string;
      };
      return manifest.version ?? '';
    }
    directory = path.dirname(directory);
  }
  throw new Error(`No package manifest found above ${entryPath}`);
}

function createDependencyFixture(root: string, conflictingVersions: boolean): {
  manifestPath: string;
  outputDirectory: string;
  ownerA: string;
  ownerB: string;
} {
  const bridgeRoot = path.join(root, 'bridge');
  const modulesDirectory = path.join(bridgeRoot, 'node_modules');
  const ownerA = path.join(modulesDirectory, 'owner-a');
  const ownerB = path.join(modulesDirectory, 'owner-b');
  writePackage(bridgeRoot, { name: '@wrzdj/bridge', dependencies: { 'owner-a': '1.0.0', 'owner-b': '1.0.0' } });
  writePackage(ownerA, { name: 'owner-a', version: '1.0.0', dependencies: { 'shared-lib': '1.0.0' } });
  writePackage(ownerB, {
    name: 'owner-b',
    version: '1.0.0',
    dependencies: { 'shared-lib': conflictingVersions ? '2.0.0' : '1.0.0' },
  });
  fs.writeFileSync(path.join(ownerA, 'index.js'), 'module.exports = require("shared-lib");\n');
  fs.writeFileSync(path.join(ownerB, 'index.js'), 'module.exports = require("shared-lib");\n');

  if (conflictingVersions) {
    writePackage(path.join(ownerA, 'node_modules/shared-lib'), {
      name: 'shared-lib', version: '1.0.0', main: 'index.js',
    });
    writePackage(path.join(ownerB, 'node_modules/shared-lib'), {
      name: 'shared-lib', version: '2.0.0', main: 'index.js',
    });
    fs.writeFileSync(path.join(ownerA, 'node_modules/shared-lib/index.js'), 'module.exports = {};\n');
    fs.writeFileSync(path.join(ownerB, 'node_modules/shared-lib/index.js'), 'module.exports = {};\n');
  } else {
    const sharedRoot = path.join(modulesDirectory, 'shared-lib');
    writePackage(sharedRoot, { name: 'shared-lib', version: '1.0.0', main: 'index.js' });
    fs.writeFileSync(path.join(sharedRoot, 'index.js'), 'module.exports = {};\n');
  }

  return {
    manifestPath: path.join(bridgeRoot, 'package.json'),
    outputDirectory: path.join(root, 'build'),
    ownerA,
    ownerB,
  };
}

function writePackage(packageRoot: string, manifest: Record<string, unknown>): void {
  fs.mkdirSync(packageRoot, { recursive: true });
  fs.writeFileSync(path.join(packageRoot, 'package.json'), JSON.stringify(manifest));
}
