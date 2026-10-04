import { defineConfig, type Plugin } from 'vite';
import path from 'path';
import fs from 'fs';

// Modules that must be externalized from the Vite bundle (loaded via require()
// at runtime). Bundling stagelinq breaks TCP connection state management and
// class name-dependent service resolution.
const externalDeps = ['stagelinq', 'alphatheta-connect'];

/**
 * Resolves the full transitive dependency tree for the given packages by
 * walking each package.json's `dependencies` field recursively.
 */
function collectTransitiveDeps(entryDeps: string[], nodeModulesDir: string): string[] {
  const all = new Set<string>();
  const queue = [...entryDeps];
  while (queue.length > 0) {
    const dep = queue.shift()!;
    if (all.has(dep)) continue;
    const depDir = path.join(nodeModulesDir, dep);
    if (!fs.existsSync(depDir)) continue;
    all.add(dep);
    const pkgPath = path.join(depDir, 'package.json');
    if (fs.existsSync(pkgPath)) {
      const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
      if (pkg.dependencies) {
        for (const d of Object.keys(pkg.dependencies)) {
          if (!all.has(d)) queue.push(d);
        }
      }
    }
  }
  return [...all];
}

/**
 * Copies externalized dependencies (and all their transitive deps) into the
 * build output's node_modules/. Forge's packageAfterCopy hook moves this staged
 * tree to the package root before native rebuilding. Required because the Vite
 * plugin excludes the project's node_modules/ (it assumes Vite bundles everything).
 */
function copyExternals(deps: string[]): Plugin {
  return {
    name: 'copy-externals',
    writeBundle(options) {
      const outDir = options.dir;
      if (!outDir) return;
      const nodeModulesDir = path.resolve(__dirname, 'node_modules');
      const allDeps = collectTransitiveDeps(deps, nodeModulesDir);
      for (const dep of allDeps) {
        const src = path.join(nodeModulesDir, dep);
        const dest = path.join(outDir, 'node_modules', dep);
        if (fs.existsSync(src)) {
          fs.cpSync(src, dest, { recursive: true, force: true });
        }
      }
    },
  };
}

export default defineConfig({
  resolve: {
    alias: {
      '@bridge': path.resolve(__dirname, '../bridge/src'),
    },
  },
  plugins: [copyExternals(externalDeps)],
  build: {
    rollupOptions: {
      external: externalDeps,
    },
  },
});
