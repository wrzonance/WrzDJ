import { describe, it, expect, vi, afterEach } from 'vitest';

// We test the module with different env combinations by re-importing after
// resetting the module registry (vi.resetModules()), so env reads happen fresh.

describe('isDevAuthBypassActive', () => {
  afterEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
  });

  it('returns false when flag is absent (default)', async () => {
    vi.stubEnv('NEXT_PUBLIC_DEV_AUTH_BYPASS', '');
    vi.stubEnv('NODE_ENV', 'development');
    const { isDevAuthBypassActive } = await import('../devAuthBypass');
    expect(isDevAuthBypassActive()).toBe(false);
  });

  it('returns true when flag is set in development', async () => {
    vi.stubEnv('NEXT_PUBLIC_DEV_AUTH_BYPASS', '1');
    vi.stubEnv('NODE_ENV', 'development');
    const { isDevAuthBypassActive } = await import('../devAuthBypass');
    expect(isDevAuthBypassActive()).toBe(true);
  });

  it('returns false when flag is set but NODE_ENV is production', async () => {
    vi.stubEnv('NEXT_PUBLIC_DEV_AUTH_BYPASS', '1');
    vi.stubEnv('NODE_ENV', 'production');
    const { isDevAuthBypassActive } = await import('../devAuthBypass');
    expect(isDevAuthBypassActive()).toBe(false);
  });

  it('returns false when flag is absent and NODE_ENV is test', async () => {
    // In Vitest runs NODE_ENV is typically "test" — bypass should still
    // be off when the flag is not set.
    vi.stubEnv('NEXT_PUBLIC_DEV_AUTH_BYPASS', '');
    vi.stubEnv('NODE_ENV', 'test');
    const { isDevAuthBypassActive } = await import('../devAuthBypass');
    expect(isDevAuthBypassActive()).toBe(false);
  });
});
