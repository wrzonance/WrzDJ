import path from 'node:path';
import fs from 'node:fs';
import type { ForgeConfig } from '@electron-forge/shared-types';
import { MakerSquirrel } from '@electron-forge/maker-squirrel';
import { MakerDMG } from '@electron-forge/maker-dmg';
import { MakerAppImage } from '@reforged/maker-appimage';
import { MakerZIP } from '@electron-forge/maker-zip';
import { VitePlugin } from '@electron-forge/plugin-vite';
import { AutoUnpackNativesPlugin } from '@electron-forge/plugin-auto-unpack-natives';

const config: ForgeConfig = {
  packagerConfig: {
    name: 'WrzDJ Bridge',
    executableName: 'wrzdj-bridge',
    icon: './resources/icon',
    asar: true,
    appBundleId: 'com.wrzdj.bridge',
  },
  makers: [
    new MakerSquirrel({
      name: 'wrzdj-bridge',
      authors: 'WrzDJ',
      description: 'DJ equipment bridge for WrzDJ song request system',
      setupIcon: './resources/icon.ico',
      setupExe: 'WrzDJ-Bridge.exe',
      noMsi: true,
      loadingGif: './resources/installing.gif',
    }),
    new MakerDMG({
      name: 'WrzDJ-Bridge',
      icon: './resources/icon.icns',
    }),
    new MakerAppImage({
      options: {
        name: 'wrzdj-bridge',
        bin: 'wrzdj-bridge',
        icon: './resources/icon.png',
        categories: ['Audio'],
      },
    }),
    new MakerZIP({}, ['darwin']),
  ],
  hooks: {
    packageAfterCopy: async (_config, buildPath) => {
      // Forge rebuilds natives in the package root's node_modules. Move the
      // staged Vite externals there before that step, so they target Electron.
      fs.renameSync(
        path.join(buildPath, '.vite', 'build', 'node_modules'),
        path.join(buildPath, 'node_modules'),
      );
    },
    postPackage: async (_config, options) => {
      if (options.platform === 'linux') {
        const outDir = options.outputPaths[0];

        // Remove chrome-sandbox — AppImages can't set SUID on the extracted binary.
        const sandboxPath = path.join(outDir, 'chrome-sandbox');
        if (fs.existsSync(sandboxPath)) {
          fs.unlinkSync(sandboxPath);
        }

        // Wrap the binary so --no-sandbox is passed as a real CLI argument.
        // Chromium's sandbox init runs before Node.js, so appendSwitch() is too late.
        const binName = 'wrzdj-bridge';
        const binPath = path.join(outDir, binName);
        const realBinPath = path.join(outDir, `${binName}.real`);
        fs.renameSync(binPath, realBinPath);
        fs.writeFileSync(
          binPath,
          `#!/bin/bash\nexec "$(dirname "$(readlink -f "$0")")/${binName}.real" --no-sandbox "$@"\n`,
          { mode: 0o755 },
        );
      }
    },
    postMake: async (_config, makeResults) => {
      const renameExts = new Set(['.dmg', '.AppImage', '.zip', '.exe', '.nupkg']);
      for (const result of makeResults) {
        for (let i = 0; i < result.artifacts.length; i++) {
          const oldPath = result.artifacts[i];
          const ext = path.extname(oldPath);
          if (renameExts.has(ext)) {
            const archSuffix = ext === '.dmg' || ext === '.zip' ? `-${result.arch}` : '';
            const newPath = path.join(path.dirname(oldPath), `WrzDJ-Bridge${archSuffix}${ext}`);
            if (oldPath !== newPath) {
              fs.renameSync(oldPath, newPath);
              result.artifacts[i] = newPath;
            }
          }
        }
      }
      return makeResults;
    },
  },
  plugins: [
    new AutoUnpackNativesPlugin({}),
    new VitePlugin({
      build: [
        {
          entry: 'src/main/main.ts',
          config: 'vite.main.config.ts',
          target: 'main',
        },
        {
          entry: 'src/preload/preload.ts',
          config: 'vite.preload.config.ts',
          target: 'preload',
        },
      ],
      renderer: [
        {
          name: 'main_window',
          config: 'vite.renderer.config.ts',
        },
      ],
    }),
  ],
};

export default config;
