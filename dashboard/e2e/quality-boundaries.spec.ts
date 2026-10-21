import { expect, test, type Page, type Route } from '@playwright/test';

async function mockApi(page: Page, role: 'admin' | 'dj' | 'pending', options?: {
  failUsageUntilRetry?: boolean;
}) {
  let usageRequests = 0;
  let usageRetryEnabled = false;
  const protectedCalls: string[] = [];
  await page.addInitScript(() => {
    localStorage.setItem('wrzdj_session_hint', 'quality-boundary-test');
  });
  await page.route('**/api/**', async (route: Route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === '/api/auth/me') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 1,
          username: 'boundary-test',
          role,
          help_pages_seen: [],
          pending_email: null,
          email: null,
          frictionless_join_default: false,
        }),
      });
    }
    if (path === '/api/admin/ai/settings') {
      return json(route, { llm_enabled: true, llm_rate_limit_per_minute: 3 });
    }
    if (path === '/api/admin/llm/policy') {
      return json(route, {
        llm_apikey_connectors_enabled: true,
        llm_compatible_connector_enabled: true,
        llm_default_connector_id: null,
        llm_call_log_retention_days: 30,
      });
    }
    if (path === '/api/admin/llm/connectors' || path === '/api/admin/llm/org-connectors') {
      return json(route, []);
    }
    if (path === '/api/admin/llm/dj-status') return json(route, { rows: [] });
    if (path === '/api/admin/llm/audit') {
      return json(route, { rows: [], total: 0, limit: 50, offset: 0 });
    }
    if (path === '/api/admin/llm/usage') {
      usageRequests += 1;
      if (options?.failUsageUntilRetry && !usageRetryEnabled) {
        return route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'local mocked usage failure' }),
        });
      }
      return json(route, { days: 30, rows: [] });
    }
    if (path === '/api/events' || path.startsWith('/api/kiosk/pair/')) {
      protectedCalls.push(path);
      return json(route, []);
    }
    return json(route, {});
  });

  return {
    protectedCalls,
    allowUsageRetry: () => { usageRetryEnabled = true; },
    usageRequestCount: () => usageRequests,
  };
}

function json(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

test('admin usage error is visible and retry shows a successful empty result', async ({ page }) => {
  // Browser regression for baseline 57cfcdc6867f; every API response is locally mocked.
  const api = await mockApi(page, 'admin', { failUsageUntilRetry: true });
  await page.goto('/admin/ai');

  await expect(page.locator('p[role="alert"]')).toHaveText('Failed to load usage.');
  api.allowUsageRetry();
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByText('No calls yet.')).toBeVisible();
  expect(api.usageRequestCount()).toBeGreaterThanOrEqual(2);
});

test('pending user is redirected before kiosk events or pairing can be requested', async ({ page }) => {
  // Browser regression for baseline 57cfcdc6867f; auth and API are local route mocks.
  const api = await mockApi(page, 'pending');
  await page.goto('/kiosk-link/ABC234');

  await expect(page).toHaveURL(/\/pending$/);
  expect(api.protectedCalls).toEqual([]);
});
