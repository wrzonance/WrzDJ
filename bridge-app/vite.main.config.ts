import { defineConfig, type Plugin } from 'vite';
import path from 'path';
import { stageBridgeDependencies } from './packaging/stage-bridge-dependencies';

// Modules that must be externalized from the Vite bundle (loaded via require()
// at runtime). Bundling stagelinq breaks TCP connection state management and
// class name-dependent service resolution.
const externalDeps = ['stagelinq', 'alphatheta-connect'];

/**
 * Copies the bridge package's production dependencies (and all their transitive deps) into the
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
      const bridgePackageManifest = path.resolve(
        __dirname,
        'node_modules/@wrzdj/bridge/package.json',
      );
      stageBridgeDependencies(bridgePackageManifest, outDir, deps);
    },
  };
}

export default defineConfig({
  resolve: {
    alias: {
      '@wrzdj/bridge/electron': path.resolve(__dirname, '../bridge/src/electron-api.ts'),
    },
  },
  plugins: [copyExternals(externalDeps)],
  build: {
    rollupOptions: {
      external: externalDeps,
    },
  },
});
