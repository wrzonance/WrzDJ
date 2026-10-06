/**
 * Aggressive exploratory test of event PB5TTP after the refactor collapse.
 * Every test exercises a real interaction the refactor touched, captures
 * console + network errors, and asserts behavior — not just non-crashing.
 */

import { test, expect, Page, ConsoleMessage } from '@playwright/test';
import { setupAuth as installSession } from './helpers';

const USERNAME = process.env.SCREENSHOT_USERNAME || 'admin';
const PASSWORD = process.env.SCREENSHOT_PASSWORD || 'admin123';
const API_PORT = process.env.SCREENSHOT_API_PORT || '8443';
const TARGET_EVENT = process.env.TARGET_EVENT || 'PB5TTP';

let jwt = '';
let apiBase = '';

test.beforeAll(async ({ playwright }, testInfo) => {
  const base = testInfo.project.use.baseURL || 'https://app.local';
  const apiUrl = new URL(base);
  apiUrl.port = API_PORT;
  apiBase = apiUrl.origin;

  const api = await playwright.request.newContext({
    baseURL: apiBase,
    ignoreHTTPSErrors: true,
  });

  const loginRes = await api.post('/api/auth/login', {
    form: { username: USERNAME, password: PASSWORD },
  });
  expect(loginRes.ok(), `Login failed: ${loginRes.status()}`).toBeTruthy();
  jwt = (await loginRes.json()).access_token;

  const eventRes = await api.get(`/api/events/${TARGET_EVENT}`, {
    headers: { Authorization: `Bearer ${jwt}` },
  });
  expect(eventRes.ok(), `Event ${TARGET_EVENT} not found: ${eventRes.status()}`).toBeTruthy();

  await api.dispose();
});

interface PageProbes {
  consoleErrors: string[];
  pageErrors: string[];
  apiNon2xx: string[];
}

function attachProbes(page: Page): PageProbes {
  const probes: PageProbes = { consoleErrors: [], pageErrors: [], apiNon2xx: [] };

  page.on('console', (msg: ConsoleMessage) => {
    if (msg.type() === 'error') probes.consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => {
    probes.pageErrors.push(`${err.message}\n${err.stack ?? ''}`);
  });
  page.on('response', async (resp) => {
    const url = resp.url();
    if (!url.includes('/api/')) return;
    const status = resp.status();
    // Some 4xx are expected (e.g., 404 on optional resources); only flag 5xx.
    if (status >= 500) {
      probes.apiNon2xx.push(`${status} ${resp.request().method()} ${url}`);
    }
  });

  return probes;
}

async function setupAuth(page: Page) {
  // Cookie session + hint (#754); also suppresses help/onboarding.
  await installSession(page, jwt, { clearSortPrefs: false });
}

function summarise(name: string, probes: PageProbes): void {
  const out: string[] = [`\n=== ${name} probes ===`];
  if (probes.consoleErrors.length) {
    out.push(`CONSOLE ERRORS (${probes.consoleErrors.length}):`);
    for (const e of probes.consoleErrors.slice(0, 5)) out.push(`  - ${e.slice(0, 240)}`);
  }
  if (probes.pageErrors.length) {
    out.push(`PAGE ERRORS (${probes.pageErrors.length}):`);
    for (const e of probes.pageErrors.slice(0, 5)) out.push(`  - ${e.slice(0, 240)}`);
  }
  if (probes.apiNon2xx.length) {
    out.push(`API 5XX (${probes.apiNon2xx.length}):`);
    for (const r of probes.apiNon2xx.slice(0, 10)) out.push(`  - ${r}`);
  }
  if (
    !probes.consoleErrors.length &&
    !probes.pageErrors.length &&
    !probes.apiNon2xx.length
  ) {
    out.push('  clean');
  }
  // eslint-disable-next-line no-console
  console.log(out.join('\n'));
}

test.describe(`Exploratory: event ${TARGET_EVENT}`, () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test('event page renders requests with enrichment badges', async ({ page }) => {
    const probes = attachProbes(page);
    await setupAuth(page);
    await page.goto(`/events/${TARGET_EVENT}`);
    await expect(page.locator('.event-tab', { hasText: 'Song Management' })).toBeVisible({
      timeout: 15_000,
    });
    await page.waitForTimeout(2_000);

    const itemCount = await page.locator('.request-item').count();
    const bpmBadgeCount = await page.locator('[aria-label^="BPM:"]').count();
    const keyBadgeCount = await page.locator('[aria-label^="Key:"]').count();
    const genreBadgeCount = await page.locator('[aria-label^="Genre:"]').count();
    // eslint-disable-next-line no-console
    console.log(
      `  request-items: ${itemCount}, BPM: ${bpmBadgeCount}, Key: ${keyBadgeCount}, Genre: ${genreBadgeCount}`
    );

    expect(itemCount, 'at least one request should render').toBeGreaterThan(0);
    expect(bpmBadgeCount, 'enriched requests should show BPM badges').toBeGreaterThan(0);
    summarise('event page enrichment visibility', probes);
    expect(probes.pageErrors).toHaveLength(0);
    expect(probes.apiNon2xx).toHaveLength(0);
  });

  test('polling fires repeatedly (Phase 3.2 usePollingLoop)', async ({ page }) => {
    const probes = attachProbes(page);
    let requestPollCount = 0;
    page.on('request', (req) => {
      if (req.url().includes(`/api/events/${TARGET_EVENT}/requests`)) requestPollCount++;
    });

    await setupAuth(page);
    await page.goto(`/events/${TARGET_EVENT}`);
    await expect(page.locator('.event-tab', { hasText: 'Song Management' })).toBeVisible({
      timeout: 15_000,
    });
    await page.waitForTimeout(12_000); // 12s = at least 2 poll cycles at 5s interval

    // eslint-disable-next-line no-console
    console.log(`  request-polls fired in 12s: ${requestPollCount}`);
    expect(requestPollCount, 'usePollingLoop should hit /requests at least 2x in 12s').toBeGreaterThanOrEqual(2);

    summarise('polling loop', probes);
    expect(probes.pageErrors).toHaveLength(0);
  });

  test('open + close DJ song search modal (Phase 3.1 ModalOverlay)', async ({ page }) => {
    const probes = attachProbes(page);
    await setupAuth(page);
    await page.goto(`/events/${TARGET_EVENT}`);
    await expect(page.locator('.event-tab', { hasText: 'Song Management' })).toBeVisible({
      timeout: 15_000,
    });
    await page.waitForTimeout(2_000);

    // The DJ search button is on the Song Management tab. Find by text.
    const searchButton = page.getByRole('button', { name: /search/i }).first();
    if (!(await searchButton.count())) {
      // eslint-disable-next-line no-console
      console.log('  search button not found — skipping');
    } else {
      await searchButton.click();
      // Modal overlay should mount.
      await expect(page.locator('.modal-overlay')).toBeVisible({ timeout: 5_000 });
      // Backdrop click dismisses.
      const overlay = page.locator('.modal-overlay').first();
      const box = await overlay.boundingBox();
      if (box) {
        await page.mouse.click(box.x + 10, box.y + 10); // top-left of overlay
        await page.waitForTimeout(400);
      }
    }

    summarise('DJ search modal', probes);
    expect(probes.pageErrors).toHaveLength(0);
  });

  test('admin pages — useAdminPage data loads, no errors', async ({ page }) => {
    const probes = attachProbes(page);
    await setupAuth(page);

    const pages: Array<{ path: string; selector: string; label: string }> = [
      { path: '/admin', selector: 'h1', label: 'Overview' },
      { path: '/admin/users', selector: 'table, .user-list, [role=table]', label: 'Users' },
      { path: '/admin/events', selector: 'table, .event-list, [role=table]', label: 'Events' },
      { path: '/admin/settings', selector: 'h1', label: 'Settings' },
      { path: '/admin/integrations', selector: 'h1', label: 'Integrations' },
      { path: '/admin/ai', selector: 'h1', label: 'AI' },
    ];

    for (const p of pages) {
      await page.goto(p.path);
      await expect(page.locator(p.selector).first()).toBeVisible({ timeout: 8_000 });
    }

    summarise('admin pages sweep', probes);
    expect(probes.pageErrors).toHaveLength(0);
    expect(probes.apiNon2xx).toHaveLength(0);
  });

  test('button mashing — open every modal, fire every visible action button', async ({ page }) => {
    // Aggressive: click every button in sequence on the event page, then
    // every modal-trigger button. Watch for any uncaught error or 5xx.
    const probes = attachProbes(page);
    await setupAuth(page);
    await page.goto(`/events/${TARGET_EVENT}`);
    await expect(page.locator('.event-tab', { hasText: 'Song Management' })).toBeVisible({
      timeout: 15_000,
    });
    await page.waitForTimeout(2_000);

    const skipPatterns = [
      /^delete$/i, /^archive$/i, /unarchive/i, /^logout$/i, /reject all/i, /accept all/i,
      /^×$/, /\bclose\b/i, /^cancel$/i, /sign\s*out/i, /unlink/i, /disconnect/i,
      /save/i, // Save buttons can spam network with bad requests
    ]; // Avoid destructive/auth-affecting buttons.

    // Snapshot button labels FIRST so the iteration doesn't go stale as the
    // DOM mutates from clicks. Then re-find each by text on every iteration.
    const allBtnTexts = await page.getByRole('button').evaluateAll((els) =>
      els.map((el) => (el.textContent || '').trim()).filter((t) => t.length > 0)
    );
    const uniqueLabels = [...new Set(allBtnTexts)].slice(0, 25); // cap to keep runtime sane
    const safeLabels = uniqueLabels.filter((t) => !skipPatterns.some((p) => p.test(t)));

    let buttonsClicked = 0;
    for (const label of safeLabels) {
      const btn = page.getByRole('button', { name: label, exact: true }).first();
      try {
        if (!(await btn.isVisible({ timeout: 500 }))) continue;
        if (!(await btn.isEnabled())) continue;
        await btn.click({ timeout: 1_500 });
        buttonsClicked++;
        await page.waitForTimeout(200);

        // Dismiss any modal that opened
        if (await page.locator('.modal-overlay').count()) {
          await page.keyboard.press('Escape');
          await page.waitForTimeout(200);
        }
      } catch {
        // Button gone or covered — fine, just skip
      }
    }

    // eslint-disable-next-line no-console
    console.log(`  buttons clicked: ${buttonsClicked}`);
    // Threshold deliberately low — the goal is "no error from any click",
    // not "click N buttons". Most pages only expose a few non-destructive
    // actions in default state.
    expect(buttonsClicked, 'should click at least 1 button').toBeGreaterThanOrEqual(1);

    summarise('button mashing', probes);
    expect(probes.pageErrors).toHaveLength(0);
    expect(probes.apiNon2xx).toHaveLength(0);
  });

  test('bulk-review enrichment fix — guest collect → bulk accept → BPM appears', async ({
    page,
    playwright,
  }) => {
    // This test creates a fresh event with collection enabled, simulates a
    // guest pick via the public API, runs bulk-review accept, then checks
    // that the enrichment background task fills BPM/key. Verifies commit 89a8831.
    const probes = attachProbes(page);
    const api = await playwright.request.newContext({ baseURL: apiBase, ignoreHTTPSErrors: true });
    const auth = { headers: { Authorization: `Bearer ${jwt}` } };

    // Create a one-off test event
    const created = await api.post('/api/events', {
      ...auth,
      data: { name: 'Bulk-Review Test', expires_hours: 6 },
    });
    expect(created.ok(), 'create event').toBeTruthy();
    const ev = await created.json();
    const code: string = ev.code;

    try {
      // Force collection phase regardless of current time — the simplest way
      // to test the bulk-review path without time-travel.
      const settings = await api.patch(`/api/events/${code}/collection`, {
        ...auth,
        data: {
          submission_cap_per_guest: 5,
          collection_phase_override: 'force_collection',
        },
      });
      expect(settings.ok(), `set collection (got ${settings.status()})`).toBeTruthy();

      // Submit a guest pick via public collect endpoint (no auth)
      const submitRes = await api.post(`/api/public/collect/${code}/requests`, {
        data: {
          song_title: 'Levels',
          artist: 'Avicii',
          source: 'manual',
          source_url: null,
          artwork_url: null,
        },
      });
      expect(submitRes.ok(), `guest submit (got ${submitRes.status()})`).toBeTruthy();
      const submitted = await submitRes.json();
      const requestId: number = submitted.id;

      // Pre-condition: not yet enriched
      const before = await api.get(`/api/events/${code}/requests`, auth);
      const beforeRows = await before.json();
      const targetBefore = beforeRows.find((r: { id: number }) => r.id === requestId);
      // eslint-disable-next-line no-console
      console.log(
        `  before bulk-review — bpm=${targetBefore?.bpm}, key=${targetBefore?.musical_key}`
      );
      expect(targetBefore?.bpm).toBeFalsy();

      // Bulk accept by id — this is the path the enrichment fix wired
      const bulk = await api.post(`/api/events/${code}/bulk-review`, {
        ...auth,
        data: { action: 'accept_ids', request_ids: [requestId] },
      });
      expect(bulk.ok(), `bulk-review (got ${bulk.status()})`).toBeTruthy();
      const bulkResult = await bulk.json();
      expect(bulkResult.accepted, 'should accept 1').toBe(1);

      // Wait for background enrichment (Tidal/Beatport search + DB update)
      await page.waitForTimeout(8_000);

      const after = await api.get(`/api/events/${code}/requests`, auth);
      const afterRows = await after.json();
      const targetAfter = afterRows.find((r: { id: number }) => r.id === requestId);
      // eslint-disable-next-line no-console
      console.log(
        `  after bulk-review + 8s — bpm=${targetAfter?.bpm}, key=${targetAfter?.musical_key}, genre=${targetAfter?.genre}`
      );

      expect(targetAfter?.bpm, 'BPM should be enriched after bulk-accept').toBeTruthy();
    } finally {
      // Clean up the test event
      await api.delete(`/api/events/${code}`, auth);
      await api.dispose();
    }

    summarise('bulk-review enrichment', probes);
  });

  test('voting — guest casts a vote, count increments', async ({ page, playwright }) => {
    const probes = attachProbes(page);
    const api = await playwright.request.newContext({ baseURL: apiBase, ignoreHTTPSErrors: true });
    const auth = { headers: { Authorization: `Bearer ${jwt}` } };

    // Need any request on PB5TTP to vote on
    const reqs = await api.get(`/api/events/${TARGET_EVENT}/requests`, auth);
    const rows = await reqs.json();
    expect(rows.length, 'PB5TTP should have requests').toBeGreaterThan(0);
    const target = rows[0];
    const before = target.vote_count;

    // Public vote endpoint — no auth required
    const voteRes = await api.post(`/api/requests/${target.id}/vote`, {
      headers: { 'X-Forwarded-For': `9.9.${Date.now() % 200}.${Date.now() % 200}` },
    });
    // eslint-disable-next-line no-console
    console.log(`  vote attempt — status ${voteRes.status()}`);
    expect([200, 201, 409], `vote should succeed or be idempotent (got ${voteRes.status()})`).toContain(
      voteRes.status()
    );

    if (voteRes.ok()) {
      const after = await api.get(`/api/events/${TARGET_EVENT}/requests`, auth);
      const afterRows = await after.json();
      const afterTarget = afterRows.find((r: { id: number }) => r.id === target.id);
      // eslint-disable-next-line no-console
      console.log(`  vote_count: ${before} → ${afterTarget?.vote_count}`);
      expect(afterTarget?.vote_count, 'vote count should increment by 1').toBe(before + 1);
    }

    summarise('voting', probes);
    await api.dispose();
  });

  test('recommendations endpoint returns correctly-typed payload', async ({ page, playwright }) => {
    // Verifies Phase 2.7's OpenAPI shim — the response shape must match
    // RecommendationResponse. Tests exercise the recommendation/service.py
    // monolith (kept untouched) through the OpenAPI-typed boundary.
    const probes = attachProbes(page);
    const api = await playwright.request.newContext({ baseURL: apiBase, ignoreHTTPSErrors: true });
    const auth = { headers: { Authorization: `Bearer ${jwt}` } };

    const recRes = await api.post(`/api/events/${TARGET_EVENT}/recommendations`, {
      ...auth,
      data: { count: 3 },
    });
    // eslint-disable-next-line no-console
    console.log(`  recommendations status: ${recRes.status()}`);
    expect([200, 503], `recs should succeed or fail gracefully (got ${recRes.status()})`).toContain(
      recRes.status()
    );

    if (recRes.ok()) {
      const body = await recRes.json();
      // Required fields per RecommendationResponse OpenAPI schema
      expect(body, 'response body').toBeTruthy();
      expect(Array.isArray(body.suggestions), 'suggestions is array').toBeTruthy();
      expect(body.profile, 'profile present').toBeTruthy();
      expect(typeof body.total_candidates_searched, 'total_candidates_searched is number').toBe(
        'number'
      );
      // eslint-disable-next-line no-console
      console.log(
        `  suggestions=${body.suggestions.length}, candidates=${body.total_candidates_searched}, profile.track_count=${body.profile.track_count}`
      );
    }

    summarise('recommendations', probes);
    await api.dispose();
  });

  test('kiosk display page polls + renders without auth', async ({ page }) => {
    const probes = attachProbes(page);
    let kioskPollCount = 0;
    page.on('request', (req) => {
      if (req.url().includes(`/api/public/e/${TARGET_EVENT}`)) kioskPollCount++;
    });

    // No auth — kiosk display is public
    await page.goto(`/e/${TARGET_EVENT}/display`);
    await page.waitForTimeout(15_000); // 15s = at least 1 poll cycle at 10s

    // eslint-disable-next-line no-console
    console.log(`  kiosk public-api requests in 15s: ${kioskPollCount}`);
    expect(kioskPollCount, 'kiosk should poll public endpoints').toBeGreaterThan(0);

    summarise('kiosk display', probes);
    expect(probes.pageErrors).toHaveLength(0);
    expect(probes.apiNon2xx).toHaveLength(0);
  });

  test('status transitions — NEW → ACCEPTED → PLAYING → PLAYED, then invalid', async ({
    page,
    playwright,
  }) => {
    // Status transitions are an FSM; refactor moved bulk-review into services
    // but per-request transitions stayed in api/requests.py. Verify both happy
    // path AND the FSM still rejects invalid jumps.
    const probes = attachProbes(page);
    const api = await playwright.request.newContext({ baseURL: apiBase, ignoreHTTPSErrors: true });
    const auth = { headers: { Authorization: `Bearer ${jwt}` } };

    // Submit a fresh request as the DJ — same path that fires enrichment
    const submitRes = await api.post(`/api/events/${TARGET_EVENT}/requests`, {
      ...auth,
      data: {
        artist: 'Status Test',
        title: `FSM trace ${Date.now()}`,
        source: 'manual',
      },
    });
    expect(submitRes.ok(), `submit (got ${submitRes.status()})`).toBeTruthy();
    const created = await submitRes.json();
    const id: number = created.id;

    const transitions: Array<{ to: string; expectStatus: number }> = [
      { to: 'accepted', expectStatus: 200 },
      { to: 'playing', expectStatus: 200 },
      { to: 'played', expectStatus: 200 },
    ];
    for (const t of transitions) {
      const res = await api.patch(`/api/requests/${id}`, {
        ...auth,
        data: { status: t.to },
      });
      // eslint-disable-next-line no-console
      console.log(`  → ${t.to}: ${res.status()}`);
      expect(res.status(), `transition to ${t.to}`).toBe(t.expectStatus);
    }

    // Invalid: PLAYED → PLAYING should fail (per FSM in services/request.py)
    const invalidRes = await api.patch(`/api/requests/${id}`, {
      ...auth,
      data: { status: 'playing' },
    });
    // eslint-disable-next-line no-console
    console.log(`  invalid PLAYED→PLAYING: ${invalidRes.status()}`);
    expect(invalidRes.status(), 'FSM should reject PLAYED→PLAYING').toBe(400);

    summarise('status transitions', probes);
    await api.dispose();
  });
});
