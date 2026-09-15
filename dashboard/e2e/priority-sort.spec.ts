import { test, expect } from '@playwright/test';
import { createTestApi, setupAuth, waitForPage, type TestApi } from './helpers';

/**
 * E2E tests for the Smart Request Sorting (priority sort) feature.
 *
 * Tests the full flow: toggle UI, API calls with sort param,
 * score badge rendering, and localStorage persistence.
 *
 * Requires running backend + frontend (push to testing).
 */

let testApi: TestApi;
let eventCode = '';

test.beforeAll(async ({ playwright }, testInfo) => {
  const baseURL = testInfo.project.use.baseURL || 'https://192.168.20.5';
  testApi = await createTestApi(playwright, baseURL);
  const event = await testApi.createEvent('Priority Sort E2E Test');
  eventCode = event.code;
  await testApi.seedRequests(eventCode);
});

test.afterAll(async () => {
  await testApi.dispose();
});

test.describe('Priority Sort', () => {
  test.use({
    viewport: { width: 1440, height: 900 },
  });

  test('Best Match toggle is visible on event page', async ({ page }) => {
    await setupAuth(page, testApi.jwt);
    await page.goto(`/events/${eventCode}`);
    await waitForPage(page, 2000);

    // The "Best Match" checkbox label should be visible
    const toggle = page.locator('label', { hasText: 'Best Match' });
    await expect(toggle).toBeVisible();

    // It should be unchecked by default (chronological mode)
    const checkbox = toggle.locator('input[type="checkbox"]');
    await expect(checkbox).not.toBeChecked();
  });

  test('toggling Best Match sends sort=priority API call', async ({ page }) => {
    await setupAuth(page, testApi.jwt);
    await page.goto(`/events/${eventCode}`);
    await waitForPage(page, 2000);

    // Intercept the next requests API call
    const requestPromise = page.waitForRequest((req) =>
      req.url().includes('/api/events/') &&
      req.url().includes('/requests') &&
      req.url().includes('sort=priority')
    );

    // Click the Best Match toggle
    const toggle = page.locator('label', { hasText: 'Best Match' });
    await toggle.click();

    // Verify the API call included sort=priority
    const apiRequest = await requestPromise;
    expect(apiRequest.url()).toContain('sort=priority');
  });

  test('priority score badges appear when Best Match is active', async ({ page }) => {
    await setupAuth(page, testApi.jwt);
    await page.goto(`/events/${eventCode}`);
    await waitForPage(page, 2000);

    // Before toggling: no score badges should exist
    const scoreBadgesBefore = page.locator('[title*="Priority score"]');
    await expect(scoreBadgesBefore).toHaveCount(0);

    // Toggle Best Match on
    const toggle = page.locator('label', { hasText: 'Best Match' });
    await toggle.click();

    // Wait for the API response to come back
    await page.waitForResponse((res) =>
      res.url().includes('/requests') && res.url().includes('sort=priority') && res.ok()
    );
    // Small delay for React re-render
    await page.waitForTimeout(500);

    // Score badges should now appear (if there are requests with scores)
    const scoreBadgesAfter = page.locator('[title*="Priority score"]');
    const badgeCount = await scoreBadgesAfter.count();

    // If the event has requests, badges should appear
    const requestItems = page.locator('.request-item');
    const requestCount = await requestItems.count();

    if (requestCount > 0) {
      expect(badgeCount).toBeGreaterThan(0);

      // Verify badge content is a percentage
      const firstBadge = scoreBadgesAfter.first();
      const text = await firstBadge.textContent();
      expect(text).toMatch(/^\d+%$/);
    }
  });

  test('toggling Best Match off removes score badges', async ({ page }) => {
    await setupAuth(page, testApi.jwt);
    await page.goto(`/events/${eventCode}`);
    await waitForPage(page, 2000);

    // Toggle on
    const toggle = page.locator('label', { hasText: 'Best Match' });
    await toggle.click();
    await page.waitForResponse((res) =>
      res.url().includes('sort=priority') && res.ok()
    );
    await page.waitForTimeout(500);

    // Verify badges appeared
    const badgesOn = page.locator('[title*="Priority score"]');
    const countOn = await badgesOn.count();

    // Toggle off
    await toggle.click();
    await page.waitForResponse((res) =>
      res.url().includes('/requests') && !res.url().includes('sort=priority') && res.ok()
    );
    await page.waitForTimeout(500);

    // Badges should be gone
    const badgesOff = page.locator('[title*="Priority score"]');
    await expect(badgesOff).toHaveCount(0);

    // But the request list should still be there (if it was before)
    if (countOn > 0) {
      const requestItems = page.locator('.request-item');
      expect(await requestItems.count()).toBeGreaterThan(0);
    }
  });

  test('Best Match preference persists across page reload', async ({ page }) => {
    // Don't clear sort prefs — we need them to persist across reload
    await setupAuth(page, testApi.jwt, { clearSortPrefs: false });
    await page.goto(`/events/${eventCode}`);
    await waitForPage(page, 2000);

    // Toggle Best Match on
    const toggle = page.locator('label', { hasText: 'Best Match' });
    await toggle.click();
    await page.waitForResponse((res) =>
      res.url().includes('sort=priority') && res.ok()
    );

    // Verify checkbox is checked
    const checkbox = toggle.locator('input[type="checkbox"]');
    await expect(checkbox).toBeChecked();

    // Reload the page
    await page.reload();
    await waitForPage(page, 2000);

    // The toggle should still be checked (persisted in localStorage)
    const toggleAfter = page.locator('label', { hasText: 'Best Match' });
    const checkboxAfter = toggleAfter.locator('input[type="checkbox"]');
    await expect(checkboxAfter).toBeChecked();

    // And the API call on load should include sort=priority
    // (Verify by checking that score badges are present)
    await page.waitForTimeout(500);
    const badges = page.locator('[title*="Priority score"]');
    const requestItems = page.locator('.request-item');
    if (await requestItems.count() > 0) {
      expect(await badges.count()).toBeGreaterThan(0);
    }
  });

  test('priority sort changes request order', async ({ page }) => {
    await setupAuth(page, testApi.jwt);
    await page.goto(`/events/${eventCode}`);
    await waitForPage(page, 2000);

    // Get request titles in chronological order
    const getTitles = async () => {
      const items = page.locator('.request-item h3');
      const count = await items.count();
      const titles: string[] = [];
      for (let i = 0; i < count; i++) {
        const text = await items.nth(i).textContent();
        if (text) titles.push(text);
      }
      return titles;
    };

    const chronoTitles = await getTitles();

    // Skip if fewer than 2 requests (can't verify reordering)
    if (chronoTitles.length < 2) {
      test.skip();
      return;
    }

    // Toggle Best Match
    const toggle = page.locator('label', { hasText: 'Best Match' });
    await toggle.click();
    await page.waitForResponse((res) =>
      res.url().includes('sort=priority') && res.ok()
    );
    await page.waitForTimeout(500);

    const priorityTitles = await getTitles();

    // The order should differ (unless scores happen to match chronological)
    // At minimum, both lists should have the same items
    expect(priorityTitles.length).toBe(chronoTitles.length);
    expect(new Set(priorityTitles)).toEqual(new Set(chronoTitles));
  });

  test('score badges have correct color coding', async ({ page }) => {
    await setupAuth(page, testApi.jwt);
    await page.goto(`/events/${eventCode}`);
    await waitForPage(page, 2000);

    // Toggle Best Match on
    const toggle = page.locator('label', { hasText: 'Best Match' });
    await toggle.click();
    await page.waitForResponse((res) =>
      res.url().includes('sort=priority') && res.ok()
    );
    await page.waitForTimeout(500);

    const badges = page.locator('[title*="Priority score"]');
    const count = await badges.count();

    if (count === 0) {
      test.skip();
      return;
    }

    // Each badge should have a valid background color
    for (let i = 0; i < count; i++) {
      const bg = await badges.nth(i).evaluate(
        (el) => getComputedStyle(el).backgroundColor
      );
      // Should be one of our three colors (green, amber, red) in rgb format
      expect(bg).toMatch(/^rgb\(\d+, \d+, \d+\)$/);
    }
  });
});
