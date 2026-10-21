import { test, expect } from '@playwright/test';
import { USERNAME, PASSWORD, setupAuth, createTestApi, waitForPage } from './helpers';

test.describe('Login & Auth', () => {
  test('successful login redirects to events dashboard', async ({ page }) => {
    await page.goto('/login');
    await waitForPage(page);

    await page.fill('#username', USERNAME);
    await page.fill('#password', PASSWORD);
    await page.click('button:has-text("Sign In")');

    await page.waitForURL('**/dashboard', { timeout: 10000 });
    expect(page.url()).toContain('/dashboard');
  });

  test('failed login shows error message', async ({ page }) => {
    await page.goto('/login');
    await waitForPage(page);

    await page.fill('#username', USERNAME);
    await page.fill('#password', 'wrong-password-12345');
    await page.click('button:has-text("Sign In")');

    // Error text should appear
    const error = page.locator('text=Invalid username or password');
    await expect(error).toBeVisible({ timeout: 5000 });
  });

  test('unauthenticated access redirects to login', async ({ page }) => {
    // Navigate to a protected page without JWT
    await page.goto('/events');
    await page.waitForURL('**/login', { timeout: 10000 });
    expect(page.url()).toContain('/login');
  });

  test('logout clears session and redirects to login', async ({ playwright, page }, testInfo) => {
    const baseURL = testInfo.project.use.baseURL || 'https://192.168.20.5';
    const testApi = await createTestApi(playwright, baseURL);

    await setupAuth(page, testApi.jwt);
    await page.goto('/events');
    await waitForPage(page);

    // Click the logout button
    await page.click('button:has-text("Logout")');

    await page.waitForURL('**/login', { timeout: 10000 });
    expect(page.url()).toContain('/login');

    await testApi.dispose();
  });
});
