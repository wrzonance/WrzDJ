import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  resolve: {
    alias: {
      '@wrzdj/bridge/electron': fileURLToPath(
        new URL('../bridge/src/electron-api.ts', import.meta.url),
      ),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: [],
    include: ['src/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      exclude: ['node_modules', 'dist', '**/*.test.{ts,tsx}', 'vitest.config.mts'],
      thresholds: {
        branches: 60,
        functions: 70,
        lines: 75,
        statements: 75,
      },
    },
  },
});
