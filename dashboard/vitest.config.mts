import { defineConfig } from 'vitest/config';
import path from 'path';
import { fileURLToPath } from 'node:url';

const configDirectory = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    include: ['**/__tests__/**/*.test.{ts,tsx}', '**/*.test.{ts,tsx}'],
    exclude: ['node_modules', '.next', 'e2e'],
    coverage: {
      provider: 'v8',
      exclude: [
        'node_modules',
        '.next',
        '**/*.test.{ts,tsx}',
        '**/__tests__/**',
        '**/*TestSupport.{ts,tsx}',
        'vitest.config.mts',
        'vitest.setup.ts',
      ],
      thresholds: {
        branches: 68,
        functions: 65,
        lines: 78,
        statements: 77,
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(configDirectory, '.'),
    },
  },
});
