import { defineConfig } from '@playwright/test';

const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:3100';
const usesExternalServer = Boolean(process.env.PLAYWRIGHT_BASE_URL);

export default defineConfig({
  testDir: './e2e',
  testMatch: ['**/smoke.spec.ts', '**/quality-boundaries.spec.ts', '**/04-search-pipeline.spec.ts'],
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  timeout: 30000,
  use: {
    baseURL,
    browserName: 'chromium',
  },
  webServer: usesExternalServer
    ? undefined
    : {
        command: 'npm run build && node scripts/start-smoke-server.mjs',
        url: baseURL,
        reuseExistingServer: false,
        timeout: 180000,
        // Exercise the local API fallback with production CSP enforced.
        env: { NEXT_PUBLIC_API_URL: '', HOSTNAME: '127.0.0.1', PORT: '3100' },
      },
});
