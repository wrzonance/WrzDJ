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

  // Regression for the Boolean(string) truthiness foot-gun: env vars are strings,
  // so a generic Boolean() check would treat "0"/"false"/"no" as enabled. The
  // gate requires an explicit "1" so those values stay OFF in dev/staging.
  it.each(['0', 'false', 'no', 'true', '2'])(
    'returns false when flag is %j (only the literal "1" enables it)',
    async (value) => {
      vi.stubEnv('NEXT_PUBLIC_DEV_AUTH_BYPASS', value);
      vi.stubEnv('NODE_ENV', 'development');
      const { isDevAuthBypassActive } = await import('../devAuthBypass');
      expect(isDevAuthBypassActive()).toBe(false);
    },
  );
});
