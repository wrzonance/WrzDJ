import { test, expect } from '@playwright/test';
import { createTestApi, waitForPage, type TestApi } from './helpers';

/**
 * Guest song request journey.
 *
 * Uses page.route() to intercept search API calls and return mock results,
 * ensuring deterministic tests regardless of external service availability.
 *
 * IMPORTANT: Tests that submit requests must use their own fresh event,
 * because the has_requested check uses IP-based fingerprinting — after
 * one submission, all subsequent browser visits from the same IP will
 * see the request list view instead of the search form.
 */

let testApi: TestApi;
let eventCode: string;

const MOCK_SEARCH_RESULTS = [
  {
    title: 'Bohemian Rhapsody',
    artist: 'Queen',
    album: 'A Night at the Opera',
    album_art: null,
    source: 'spotify',
    source_url: 'https://open.spotify.com/track/mock1',
    popularity: 95,
    bpm: null,
    musical_key: null,
  },
  {
    title: 'Don\'t Stop Me Now',
    artist: 'Queen',
    album: 'Jazz',
    album_art: null,
    source: 'spotify',
    source_url: 'https://open.spotify.com/track/mock2',
    popularity: 90,
    bpm: null,
    musical_key: null,
  },
];

test.beforeAll(async ({ playwright }, testInfo) => {
  const baseURL = testInfo.project.use.baseURL || 'https://192.168.20.5';
  testApi = await createTestApi(playwright, baseURL);
  // Shared event for read-only tests (no submission)
  const event = await testApi.createEvent('E2E-GUEST-Test');
  eventCode = event.code;
});

test.afterAll(async () => {
  await testApi.dispose();
});

/** Intercept search API and return mock results */
async function mockSearchApi(page: import('@playwright/test').Page) {
  await page.route('**/api/events/*/search**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_SEARCH_RESULTS),
    });
  });
}

test.describe('Guest Request Flow', () => {
  test('guest sees event name and search form', async ({ page }) => {
    await page.goto(`/join/${eventCode}`);
    await waitForPage(page);

    const searchInput = page.locator('input[placeholder*="Search for a song or artist"]');
    await expect(searchInput).toBeVisible({ timeout: 10000 });

    const searchButton = page.locator('button:has-text("Search")');
    await expect(searchButton).toBeVisible();
  });

  test('search returns results', async ({ page }) => {
    await mockSearchApi(page);
    await page.goto(`/join/${eventCode}`);
    await waitForPage(page);

    await page.fill('input[placeholder*="Search for a song or artist"]', 'Queen');
    await page.click('button:has-text("Search")');

    const results = page.locator('.request-item');
    await expect(results.first()).toBeVisible({ timeout: 5000 });
    expect(await results.count()).toBe(2);
  });

  test('selecting a song shows confirmation form', async ({ page }) => {
    await mockSearchApi(page);
    await page.goto(`/join/${eventCode}`);
    await waitForPage(page);

    await page.fill('input[placeholder*="Search for a song or artist"]', 'Queen');
    await page.click('button:has-text("Search")');

    const firstResult = page.locator('.request-item').first();
    await expect(firstResult).toBeVisible({ timeout: 5000 });
    await firstResult.click();

    const submitBtn = page.locator('button:has-text("Submit Request")');
    await expect(submitBtn).toBeVisible({ timeout: 3000 });

    const noteInput = page.locator('#note');
    await expect(noteInput).toBeVisible();
  });

  test('submitting request shows success message', async ({ page }) => {
    // Fresh event — submission creates a fingerprint record for this IP
    const submitEvent = await testApi.createEvent('E2E-GUEST-Submit');

    await mockSearchApi(page);
    await page.goto(`/join/${submitEvent.code}`);
    await waitForPage(page);

    await page.fill('input[placeholder*="Search for a song or artist"]', 'Queen');
    await page.click('button:has-text("Search")');

    const firstResult = page.locator('.request-item').first();
    await expect(firstResult).toBeVisible({ timeout: 5000 });
    await firstResult.click();

    const submitBtn = page.locator('button:has-text("Submit Request")');
    await expect(submitBtn).toBeVisible({ timeout: 3000 });
    await submitBtn.click();

    const success = page.locator('text=/Request Submitted!|Vote Added!/');
    await expect(success).toBeVisible({ timeout: 5000 });
  });

  test('guest request list is visible after submission', async ({ page }) => {
    // Fresh event — this test submits and then checks the request list
    const listEvent = await testApi.createEvent('E2E-GUEST-List');

    await mockSearchApi(page);
    await page.goto(`/join/${listEvent.code}`);
    await waitForPage(page);

    await page.fill('input[placeholder*="Search for a song or artist"]', 'Queen');
    await page.click('button:has-text("Search")');

    const firstResult = page.locator('.request-item').first();
    await expect(firstResult).toBeVisible({ timeout: 5000 });
    await firstResult.click();

    const submitBtn = page.locator('button:has-text("Submit Request")');
    await expect(submitBtn).toBeVisible({ timeout: 3000 });
    await submitBtn.click();

    // Wait for the confirmation to fade out and request list to appear
    const requestList = page.locator('.guest-request-list');
    await expect(requestList).toBeVisible({ timeout: 10000 });

    const items = page.locator('.guest-request-item');
    expect(await items.count()).toBeGreaterThan(0);
  });
});
