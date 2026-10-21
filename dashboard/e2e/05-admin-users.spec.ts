import { test, expect, type Page } from '@playwright/test';
import { createTestApi, setupAuth, waitForPage, type TestApi } from './helpers';

/**
 * Admin dashboard E2E tests — user management, overview stats, settings.
 */

let testApi: TestApi;

interface UserListResponse {
  items: Array<{ username: string }>;
}

function waitForUserListResponse(page: Page, role: string | null) {
  return page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname.endsWith('/api/admin/users') &&
      url.searchParams.get('role') === role &&
      response.ok()
    );
  });
}

test.beforeAll(async ({ playwright }, testInfo) => {
  const baseURL = testInfo.project.use.baseURL || 'https://192.168.20.5';
  testApi = await createTestApi(playwright, baseURL);
});

test.afterAll(async () => {
  await testApi.dispose();
});

test.describe('Admin Dashboard', () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test('admin users page loads with user list', async ({ page }) => {
    await setupAuth(page, testApi.jwt);
    await page.goto('/admin/users');
    await waitForPage(page);

    // User table should be visible
    const table = page.locator('.admin-table');
    await expect(table).toBeVisible({ timeout: 10000 });

    // At least the admin user should be listed
    const rows = page.locator('.admin-table tbody tr');
    await expect.poll(() => rows.count()).toBeGreaterThan(0);
  });

  test('role filter tabs work', async ({ page }) => {
    await setupAuth(page, testApi.jwt);
    await page.goto('/admin/users');
    await waitForPage(page);

    // Click "Admins" tab
    const adminsTab = page.locator('button.tab', { hasText: 'Admins' });
    const adminsResponse = waitForUserListResponse(page, 'admin');
    await adminsTab.click();
    await expect(adminsTab).toHaveClass(/active/);
    const adminUsers = (await (await adminsResponse).json()) as UserListResponse;

    // Rendered rows should match the filtered server response.
    const rows = page.locator('.admin-table tbody tr');
    const adminUsernames = adminUsers.items.map(({ username }) => username);
    await expect
      .poll(() => rows.locator('td:first-child').allTextContents())
      .toEqual(adminUsernames);

    // Each visible role badge should be admin
    const roleBadges = page.locator('.badge-role-admin');
    await expect.poll(async () => {
      const rowCount = await rows.count();
      return rowCount > 0 && (await roleBadges.count()) === rowCount;
    }).toBe(true);

    // Click "All" to reset
    const allTab = page.locator('button.tab', { hasText: 'All' });
    const allResponse = waitForUserListResponse(page, null);
    await allTab.click();
    await expect(allTab).toHaveClass(/active/);
    const allUsers = (await (await allResponse).json()) as UserListResponse;

    const allRows = page.locator('.admin-table tbody tr');
    const allUsernames = allUsers.items.map(({ username }) => username);
    await expect
      .poll(() => allRows.locator('td:first-child').allTextContents())
      .toEqual(allUsernames);
  });

  test('overview stats are populated', async ({ page }) => {
    await setupAuth(page, testApi.jwt);
    await page.goto('/admin');
    await waitForPage(page);

    // Stats grid should be visible
    const statsGrid = page.locator('.stats-grid');
    await expect(statsGrid).toBeVisible({ timeout: 10000 });

    // Stat cards should have numeric values
    const statValues = page.locator('.stat-value');
    await expect.poll(() => statValues.count()).toBeGreaterThan(0);

    // At least one stat should show a number > 0 (we have users and events)
    await expect(statValues.first()).toHaveText(/\d+/);
  });

  test('settings page loads with toggle elements', async ({ page }) => {
    await setupAuth(page, testApi.jwt);
    await page.goto('/admin/settings');
    await waitForPage(page);

    // Self-Registration toggle should be visible
    const regLabel = page.locator('text=Self-Registration');
    await expect(regLabel).toBeVisible({ timeout: 10000 });

    // Save Settings button should be present
    const saveBtn = page.locator('button:has-text("Save Settings")');
    await expect(saveBtn).toBeVisible();
  });
});
