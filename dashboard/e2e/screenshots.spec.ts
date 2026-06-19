import path from 'path';
import { test, expect } from '@playwright/test';

const USERNAME = process.env.SCREENSHOT_USERNAME || 'admin';
const PASSWORD = process.env.SCREENSHOT_PASSWORD || 'admin123';
const API_PORT = process.env.SCREENSHOT_API_PORT || '8443';
// SCREENSHOT_EVENT_CODE targets a specific event by its collection code; otherwise the
// pre-seeded DEMO01 (then a throwaway event) is used. SCREENSHOT_FRICTIONLESS=1 tells the
// guest tests the event skips the nickname gate (auto-named guests).
const EVENT_CODE = process.env.SCREENSHOT_EVENT_CODE || '';
const FRICTIONLESS = process.env.SCREENSHOT_FRICTIONLESS === '1';
const SCREENSHOTS_DIR = path.resolve(__dirname, '../../docs/images');

let jwt = '';
// Collection code drives DJ/collect surfaces; join code drives guest /join + kiosk /display.
let collectionCode = '';
let joinCode = '';

test.beforeAll(async ({ playwright }, testInfo) => {
  const base = testInfo.project.use.baseURL || 'https://app.local';
  const apiUrl = new URL(base);
  apiUrl.port = API_PORT;

  const api = await playwright.request.newContext({
    baseURL: apiUrl.origin,
    ignoreHTTPSErrors: true,
  });

  // Authenticate
  const loginRes = await api.post('/api/auth/login', {
    form: {
      username: USERNAME,
      password: PASSWORD,
    },
  });
  expect(loginRes.ok(), `Login failed: ${loginRes.status()}`).toBeTruthy();
  const loginData = await loginRes.json();
  jwt = loginData.access_token;

  // Resolve the event to screenshot. Prefer SCREENSHOT_EVENT_CODE, then the pre-seeded
  // DEMO01 (server/scripts/seed_demo_event.py), then a throwaway event. Capture BOTH codes:
  // the collection code (DJ dashboard + /collect) and the join code (/join + kiosk /display).
  async function loadEvent(code: string) {
    const res = await api.get(`/api/events/${code}`, {
      headers: { Authorization: `Bearer ${jwt}` },
    });
    if (!res.ok()) return null;
    const e = await res.json();
    return { collection: e.code as string, join: e.join_code as string };
  }

  let resolved = EVENT_CODE ? await loadEvent(EVENT_CODE) : null;
  if (!resolved) resolved = await loadEvent('DEMO01');
  if (!resolved) {
    const createRes = await api.post('/api/events', {
      headers: { Authorization: `Bearer ${jwt}` },
      data: { name: 'demo' },
    });
    expect(createRes.ok()).toBeTruthy();
    const created = await createRes.json();
    resolved = { collection: created.code, join: created.join_code };
  }
  collectionCode = resolved.collection;
  joinCode = resolved.join;

  await api.dispose();
});

async function setupAuth(page: import('@playwright/test').Page) {
  if (!jwt) throw new Error('beforeAll did not run or login failed — jwt is empty');
  await page.addInitScript((token: string) => {
    localStorage.setItem('token', token);
    // Suppress help/onboarding for clean screenshots
    localStorage.setItem('wrzdj-help-disabled', '1');
  }, jwt);
}

async function ensureCleanUI(page: import('@playwright/test').Page) {
  // Dismiss any active overlay (safety net)
  await page.keyboard.press('Escape');
  await page.waitForTimeout(200);
}

async function waitForPage(page: import('@playwright/test').Page) {
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(800);
}

async function capture(
  page: import('@playwright/test').Page,
  name: string,
  opts: { fullPage?: boolean } = {},
) {
  await page.screenshot({
    path: path.join(SCREENSHOTS_DIR, `${name}.png`),
    fullPage: opts.fullPage ?? true,
  });
}

// --- Authenticated pages (1440x900 desktop) ---

test.describe('Authenticated pages', () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test('DJ Dashboard', async ({ page }) => {
    await setupAuth(page);
    await page.goto('/dashboard');
    await waitForPage(page);
    await ensureCleanUI(page);
    await capture(page, 'screenshot-dashboard');
  });

  test('Events List', async ({ page }) => {
    await setupAuth(page);
    await page.goto('/events');
    await waitForPage(page);
    await ensureCleanUI(page);
    await capture(page, 'screenshot-events-list');
  });

  test('Event Management — Song Tab', async ({ page }) => {
    await setupAuth(page);
    await page.goto(`/events/${collectionCode}`);
    await waitForPage(page);
    await ensureCleanUI(page);
    await capture(page, 'screenshot-event-management');
  });

  test('Event Management — Manage Tab', async ({ page }) => {
    await setupAuth(page);
    await page.goto(`/events/${collectionCode}`);
    await waitForPage(page);
    await ensureCleanUI(page);
    await page.click('.event-tab:has-text("Event Management")');
    await page.waitForTimeout(500);
    await capture(page, 'screenshot-event-management-tab');
  });

  test('Admin Overview', async ({ page }) => {
    await setupAuth(page);
    await page.goto('/admin');
    await waitForPage(page);
    await ensureCleanUI(page);
    await capture(page, 'screenshot-admin-overview');
  });

  test('Admin Users', async ({ page }) => {
    await setupAuth(page);
    await page.goto('/admin/users');
    await waitForPage(page);
    await ensureCleanUI(page);
    await capture(page, 'screenshot-admin-users');
  });

  test('Admin Integrations', async ({ page }) => {
    await setupAuth(page);
    await page.goto('/admin/integrations');
    await waitForPage(page);
    await ensureCleanUI(page);
    await capture(page, 'screenshot-admin-integrations');
  });

  test('Admin Settings', async ({ page }) => {
    await setupAuth(page);
    await page.goto('/admin/settings');
    await waitForPage(page);
    await ensureCleanUI(page);
    await capture(page, 'screenshot-admin-settings');
  });
});

// --- Public pages ---

// Token from server/scripts/seed_demo_event.py — drops the NicknameGate so we capture
// the actual Tower v2 styled UI behind it.
const DEMO_GUEST_TOKEN =
  'demoguest0000000000000000000000000000000000000000000000000demo';

async function newGuestContext(browser: import('@playwright/test').Browser, baseURL: string) {
  const ctx = await browser.newContext({
    viewport: { width: 430, height: 844 },
    ignoreHTTPSErrors: true,
  });
  const url = new URL(baseURL);
  await ctx.addCookies([
    {
      name: 'wrzdj_guest',
      value: DEMO_GUEST_TOKEN,
      domain: url.hostname,
      path: '/',
      secure: true,
      sameSite: 'Lax',
    },
  ]);
  return ctx;
}

test.describe('Public pages', () => {
  test('Guest Join — gate (mobile)', async ({ browser }) => {
    test.skip(FRICTIONLESS, 'Frictionless join has no nickname gate to capture.');
    // No cookie — captures the unauthenticated NicknameGate.
    const ctx = await browser.newContext({
      viewport: { width: 430, height: 844 },
      ignoreHTTPSErrors: true,
    });
    const page = await ctx.newPage();
    await page.goto(`/join/${joinCode}`);
    await waitForPage(page);
    await capture(page, 'screenshot-join-gate-mobile');
    await ctx.close();
  });

  test('Guest Join — Tower (mobile)', async ({ browser }, testInfo) => {
    const baseURL = testInfo.project.use.baseURL || 'https://app.local';
    // Frictionless events auto-name the guest on load (no gate, no cookie needed);
    // otherwise drop the seed's demo guest cookie to bypass the NicknameGate.
    const ctx = FRICTIONLESS
      ? await browser.newContext({ viewport: { width: 430, height: 844 }, ignoreHTTPSErrors: true })
      : await newGuestContext(browser, baseURL);
    const page = await ctx.newPage();
    await page.goto(`/join/${joinCode}`);
    await waitForPage(page);
    await page.waitForTimeout(700);
    // Frictionless auto-opens the "Request a song" sheet for guests with no requests yet;
    // close it so the live queue (Tower) is what we capture.
    const closeBtn = page.locator('button[aria-label="Close"]').first();
    if ((await closeBtn.count()) > 0) {
      await closeBtn.click().catch(() => {});
      await page.waitForTimeout(400);
    }
    await capture(page, 'screenshot-join-mobile');

    // Open song detail sheet — first request row (best-effort: the live SSE list can
    // re-render under the cursor, so don't fail the run if the click can't settle).
    const firstRow = page.locator('.gst-tower-row').first();
    if ((await firstRow.count()) > 0) {
      try {
        await firstRow.click({ timeout: 4000 });
        await page.waitForTimeout(500);
        await capture(page, 'screenshot-join-detail-mobile');
      } catch {
        /* detail sheet is optional */
      }
    }
    await ctx.close();
  });

  test('Guest Collect — Tower (mobile)', async ({ browser }, testInfo) => {
    const baseURL = testInfo.project.use.baseURL || 'https://app.local';
    const ctx = FRICTIONLESS
      ? await browser.newContext({ viewport: { width: 430, height: 844 }, ignoreHTTPSErrors: true })
      : await newGuestContext(browser, baseURL);
    const page = await ctx.newPage();
    await page.goto(`/collect/${collectionCode}`);
    await waitForPage(page);
    await page.waitForTimeout(700);
    await capture(page, 'screenshot-collect-mobile');

    const firstRow = page.locator('.gst-collect-row').first();
    if ((await firstRow.count()) > 0) {
      await firstRow.click();
      await page.waitForTimeout(500);
      await capture(page, 'screenshot-collect-detail-mobile');
    }
    await ctx.close();
  });

  test('Kiosk Display', async ({ browser }) => {
    const ctx = await browser.newContext({
      viewport: { width: 1920, height: 1080 },
      ignoreHTTPSErrors: true,
    });
    const page = await ctx.newPage();
    await page.goto(`/e/${joinCode}/display`);
    await waitForPage(page);
    await capture(page, 'screenshot-kiosk', { fullPage: false });
    await ctx.close();
  });
});
