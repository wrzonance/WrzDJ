/**
 * DEV-ONLY guest-gate bypass for headless Playwright testing.
 *
 * SECURITY: Double-gated —
 *   1. Build-time: NEXT_PUBLIC_DEV_AUTH_BYPASS must be truthy (baked into the
 *      bundle at `next build` time; absent in production builds by default).
 *   2. Runtime: NODE_ENV must not be 'production'.
 *
 * A production build where the env var is somehow present still gets
 * NODE_ENV === 'production', so the bypass is INERT by construction.
 * The backend enforces its own DEV_AUTH_BYPASS gate independently.
 *
 * Mirror of the backend `Settings.auth_bypass_enabled` property in
 * server/app/core/config.py.
 */
export function isDevAuthBypassActive(): boolean {
  const flagSet = Boolean(process.env.NEXT_PUBLIC_DEV_AUTH_BYPASS);
  const notProd = process.env.NODE_ENV !== 'production';
  return flagSet && notProd;
}
