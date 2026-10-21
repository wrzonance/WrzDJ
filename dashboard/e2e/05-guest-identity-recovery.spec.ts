import { test, expect } from '@playwright/test';
import { createTestApi, waitForPage, type TestApi } from './helpers';

/**
 * Guest identity recovery flow — EmailRecoveryButton + EmailRecoveryModal
 * on the /collect/{code} page.
 *
 * The collect page renders behind a NicknameGate that waits for:
 *   1. /api/public/guest/identify  (sets wrzdj_guest cookie)
 *   2. /api/public/collect/{code}/profile  (returns guest profile)
 *
 * When the profile endpoint returns 404 the gate calls onComplete with empty
 * data and unmounts — the main collect page (with EmailRecoveryButton) renders.
 * We additionally mock the event preview and leaderboard endpoints so the page
 * reaches steady state without needing a real collection-phase event.
 */

let testApi: TestApi;
let eventCode: string;

const MOCK_EVENT_PREVIEW = {
  id: 1,
  code: 'REPLACED_BELOW',
  name: 'E2E Recovery Test Event',
  phase: 'collection',
  submission_cap_per_guest: 5,
  banner_url: null,
  collection_opens_at: null,
  live_starts_at: null,
};

const MOCK_LEADERBOARD = { requests: [] };
const MOCK_MY_PICKS = {
  submitted: [],
  upvoted: [],
  is_top_contributor: false,
  first_suggestion_ids: [],
  voted_request_ids: [],
};

test.beforeAll(async ({ playwright }, testInfo) => {
  const baseURL = testInfo.project.use.baseURL || 'https://192.168.20.5';
  testApi = await createTestApi(playwright, baseURL);
  const event = await testApi.createEvent('E2E-Recovery-Test');
  eventCode = event.code;
});

test.afterAll(async () => {
  await testApi.dispose();
});

/**
 * Set up all the API mocks needed to get past the NicknameGate and render
 * the main collect page with EmailRecoveryButton visible.
 *
 * - identify: returns a normal create action, no reconcile_hint by default
 * - profile:  returns 404 so NicknameGate calls onComplete immediately
 * - event:    returns a collection-phase event preview
 * - leaderboard / my-picks: return empty lists
 */
async function mockCollectApis(
  page: import('@playwright/test').Page,
  options: { reconcileHint?: boolean } = {},
) {
  const { reconcileHint = false } = options;

  // 1. Guest identity — always intercept before page load
  await page.route('**/api/public/guest/identify', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        guest_id: 1,
        action: 'create',
        reconcile_hint: reconcileHint,
      }),
    }),
  );

  // 2. Profile — 404 bypasses the nickname/email gate immediately
  await page.route('**/api/public/collect/*/profile/me', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_MY_PICKS),
    }),
  );

  await page.route('**/api/public/collect/*/profile', (route) => {
    // Only 404 on GET (the NicknameGate check); don't intercept POSTs
    if (route.request().method() === 'GET') {
      return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
    }
    return route.continue();
  });

  // 3. Event preview
  await page.route('**/api/public/collect/*', (route) => {
    // Only intercept the base event preview (not leaderboard or profile sub-paths)
    const url = route.request().url();
    if (!url.includes('/leaderboard') && !url.includes('/profile')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...MOCK_EVENT_PREVIEW, code: eventCode }),
      });
    }
    return route.continue();
  });

  // 4. Leaderboard
  await page.route('**/api/public/collect/*/leaderboard**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_LEADERBOARD),
    }),
  );
}

test.describe('Guest identity recovery flow', () => {
  test('passive recovery button visible on /collect/{code}', async ({ page }) => {
    await mockCollectApis(page, { reconcileHint: false });
    await page.goto(`/collect/${eventCode}`);
    await waitForPage(page);

    // The passive variant renders "Already have an account?" text
    await expect(page.getByText(/already have an account/i)).toBeVisible({ timeout: 8000 });
  });

  test('emphasized banner appears when reconcile_hint=true', async ({ page }) => {
    await mockCollectApis(page, { reconcileHint: true });
    await page.goto(`/collect/${eventCode}`);
    await waitForPage(page);

    await expect(
      page.getByText(/looks like you might be a returning guest/i),
    ).toBeVisible({ timeout: 8000 });
  });

  test('clicking the recovery button opens the dialog', async ({ page }) => {
    await mockCollectApis(page, { reconcileHint: false });
    await page.goto(`/collect/${eventCode}`);
    await waitForPage(page);

    // Passive state: the inline link button is labelled "Verify email"
    await page.getByRole('button', { name: /^verify email$/i }).first().click();
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 5000 });
  });

  test('ESC closes the recovery modal', async ({ page }) => {
    await mockCollectApis(page, { reconcileHint: false });
    await page.goto(`/collect/${eventCode}`);
    await waitForPage(page);

    await page.getByRole('button', { name: /^verify email$/i }).first().click();
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 5000 });

    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).not.toBeVisible({ timeout: 5000 });
  });

  test('full recovery flow: email -> code -> modal closes -> identity refreshed', async ({ page }) => {
    // Set up baseline mocks first (event, leaderboard, profile, etc.)
    await mockCollectApis(page, { reconcileHint: false });

    // Override identify with a counter — first call returns guest 42 (initial load),
    // subsequent calls (after merge reload) return guest 99.
    let identifyCallCount = 0;
    await page.route('**/api/public/guest/identify', (route) => {
      identifyCallCount += 1;
      const guest_id = identifyCallCount === 1 ? 42 : 99;
      const action = identifyCallCount === 1 ? 'create' : 'cookie_hit';
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ guest_id, action, reconcile_hint: false }),
      });
    });

    // Mock verify/request — just acknowledges the email was sent
    await page.route('**/api/public/guest/verify/request', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ sent: true }),
      }),
    );

    // Mock verify/confirm — returns a successful merge so merged=true triggers reload
    await page.route('**/api/public/guest/verify/confirm', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ verified: true, guest_id: 99, merged: true }),
      }),
    );

    await page.goto(`/collect/${eventCode}`);
    await waitForPage(page);

    // Open the recovery modal via the passive "Verify email" button
    await page.getByRole('button', { name: /^verify email$/i }).first().click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible({ timeout: 5000 });

    // EmailVerification renders a plain <input type="email"> with no associated label —
    // locate it directly by type, scoped to the dialog.
    await dialog.locator('input[type="email"]').fill('returning@example.com');
    await dialog.getByRole('button', { name: /send code/i }).click();

    // Wait for the 6 digit inputs to appear (component transitions to 'code_sent' state).
    // Inputs are <input type="text" inputMode="numeric"> — one per digit.
    const digitInputs = dialog.locator('input[inputmode="numeric"]');
    await expect(digitInputs.first()).toBeVisible({ timeout: 5000 });

    // Fill each digit individually. The component auto-submits via useEffect when all
    // 6 slots are filled — there is no explicit "Verify" button to click.
    const code = '123456';
    for (let i = 0; i < 6; i++) {
      await digitInputs.nth(i).fill(code[i]);
    }

    // merged=true causes window.location.reload() inside EmailVerification.confirmCode().
    // The reload destroys the current DOM — dialog will no longer be present.
    // Wait for the navigation to complete (reload triggers a full page load).
    await page.waitForLoadState('load', { timeout: 10000 });

    // Identity was refreshed — the page called identify at least twice
    // (once on initial load, at least once after the merge reload).
    expect(identifyCallCount).toBeGreaterThanOrEqual(2);
  });
});
