import { test, expect } from '@playwright/test';
import { createTestApi, setupAuth, waitForPage, TEST_TRACKS, type TestApi } from './helpers';

/**
 * DJ event management — request lifecycle, bulk actions, and filter tabs.
 */

let testApi: TestApi;
let eventCode: string;

test.beforeAll(async ({ playwright }, testInfo) => {
  const baseURL = testInfo.project.use.baseURL || 'https://192.168.20.5';
  testApi = await createTestApi(playwright, baseURL);
  const event = await testApi.createEvent('E2E-DJ-Mgmt-Test');
  eventCode = event.code;
  await testApi.seedRequests(eventCode);
});

test.afterAll(async () => {
  await testApi.dispose();
});

test.describe('DJ Event Management', () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test('event page shows request list with correct count', async ({ page }) => {
    await setupAuth(page, testApi.jwt);
    await page.goto(`/events/${eventCode}`);
    await waitForPage(page);

    // The "All" tab should show the total count
    const allTab = page.locator('button.tab', { hasText: 'All' });
    await expect(allTab).toBeVisible();
    await expect(allTab).toContainText(String(TEST_TRACKS.length));

    // Request items should be listed
    const items = page.locator('.request-item');
    await expect(items).toHaveCount(TEST_TRACKS.length);
  });

  test('accept request changes status badge', async ({ page }) => {
    // Use a fresh event so we have a known state
    const acceptEvent = await testApi.createEvent('E2E-DJ-Accept');
    await testApi.seedRequests(acceptEvent.code);

    await setupAuth(page, testApi.jwt);
    await page.goto(`/events/${acceptEvent.code}`);
    await waitForPage(page);

    // Get the first request item's ID to track it after status change
    const firstItem = page.locator('.request-item').first();
    await expect(firstItem).toBeVisible();
    const itemId = await firstItem.getAttribute('id');

    // Click Accept on the first request
    await firstItem.locator('button:has-text("Accept")').click();

    // Wait for the badge to change on that specific item (by ID)
    const trackedItem = page.locator(`#${itemId}`);
    const acceptedBadge = trackedItem.locator('.badge-accepted');
    await expect(acceptedBadge).toBeVisible({ timeout: 5000 });
  });

  test('reject request changes status badge', async ({ page }) => {
    const rejectEvent = await testApi.createEvent('E2E-DJ-Reject');
    await testApi.seedRequests(rejectEvent.code);

    await setupAuth(page, testApi.jwt);
    await page.goto(`/events/${rejectEvent.code}`);
    await waitForPage(page);

    // Get the first request item's ID
    const firstItem = page.locator('.request-item').first();
    await expect(firstItem).toBeVisible();
    const itemId = await firstItem.getAttribute('id');

    await firstItem.locator('button:has-text("Reject")').click();

    // Track by ID since badge-new filter will stop matching
    const trackedItem = page.locator(`#${itemId}`);
    const rejectedBadge = trackedItem.locator('.badge-rejected');
    await expect(rejectedBadge).toBeVisible({ timeout: 5000 });
  });

  test('Mark Playing transitions request to playing state', async ({ page }) => {
    // Use a fresh event with a pre-accepted request for deterministic state
    const playingEvent = await testApi.createEvent('E2E-DJ-MarkPlaying');
    await testApi.seedRequests(playingEvent.code);
    const requests = await testApi.getRequests(playingEvent.code);
    await testApi.updateRequestStatus(playingEvent.code, requests[0].id, 'accepted');

    await setupAuth(page, testApi.jwt);
    await page.goto(`/events/${playingEvent.code}`);
    await waitForPage(page);

    // Find the accepted request and capture its DOM ID before clicking
    const acceptedItem = page.locator('.request-item').filter({ has: page.locator('.badge-accepted') }).first();
    await expect(acceptedItem).toBeVisible({ timeout: 5000 });
    const itemId = await acceptedItem.getAttribute('id');

    await acceptedItem.locator('button:has-text("Mark Playing")').click();

    // Track by ID since badge-accepted filter will stop matching
    const trackedItem = page.locator(`#${itemId}`);
    const playingBadge = trackedItem.locator('.badge-playing');
    await expect(playingBadge).toBeVisible({ timeout: 5000 });
  });

  test('Accept All bulk action accepts remaining new requests', async ({ page }) => {
    // Create a fresh event for this test to ensure we have new requests
    const freshEvent = await testApi.createEvent('E2E-DJ-AcceptAll');
    await testApi.seedRequests(freshEvent.code);

    await setupAuth(page, testApi.jwt);
    await page.goto(`/events/${freshEvent.code}`);
    await waitForPage(page);

    // Click "Accept All" button
    const acceptAllBtn = page.locator('button:has-text("Accept All")');
    await expect(acceptAllBtn).toHaveText(`Accept All (${TEST_TRACKS.length})`);
    await acceptAllBtn.click();

    // The "New" tab count should now be 0
    const newTab = page.locator('button.tab', { hasText: 'New' });
    await expect(newTab).toContainText('0');
    await expect(page.locator('.request-item .badge-accepted')).toHaveCount(TEST_TRACKS.length);
  });

  test('filter tabs show correct filtered results', async ({ page }) => {
    // Create event with requests in different states
    const filterEvent = await testApi.createEvent('E2E-DJ-Filters');
    await testApi.seedRequests(filterEvent.code);

    // Accept 2 requests via API
    const requests = await testApi.getRequests(filterEvent.code);
    await testApi.updateRequestStatus(filterEvent.code, requests[0].id, 'accepted');
    await testApi.updateRequestStatus(filterEvent.code, requests[1].id, 'accepted');

    await setupAuth(page, testApi.jwt);
    await page.goto(`/events/${filterEvent.code}`);
    await waitForPage(page);

    // "Accepted" tab should show 2
    const acceptedTab = page.locator('button.tab', { hasText: 'Accepted' });
    await acceptedTab.click();
    await expect(acceptedTab).toHaveClass(/active/);

    const acceptedItems = page.locator('.request-item');
    await expect(acceptedItems).toHaveCount(2);

    // "New" tab should show remaining 2
    const newTab = page.locator('button.tab', { hasText: 'New' });
    await newTab.click();
    await expect(newTab).toHaveClass(/active/);

    const newItems = page.locator('.request-item');
    await expect(newItems).toHaveCount(2);
  });
});
