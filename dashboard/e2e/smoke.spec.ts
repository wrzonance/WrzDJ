import { expect, test } from '@playwright/test';

test('login page renders its form without an external API', async ({ page }) => {
  await page.route('**/api/auth/settings', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ registration_enabled: false, turnstile_site_key: '' }),
    }),
  );
  await page.goto('/login');

  await expect(page.getByRole('heading', { name: 'WrzDJ Login' })).toBeVisible();
  await expect(page.getByLabel('Username')).toBeVisible();
  await expect(page.getByLabel('Password')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Sign In' })).toBeVisible();
});

test('all dashboard font roles load from local variable font assets', async ({ page }) => {
  const fontRequests: string[] = [];
  page.on('request', (request) => {
    if (request.resourceType() === 'font') fontRequests.push(request.url());
  });

  await page.route('**/api/auth/settings', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ registration_enabled: false, turnstile_site_key: '' }),
    }),
  );
  await page.goto('/login');
  await page.evaluate(async () => {
    const roles = ['body', 'display', 'mono', 'grotesk'];
    await Promise.all(
      roles.map(async (role) => {
        const fontList = getComputedStyle(document.documentElement)
          .getPropertyValue(`--font-${role}`)
          .trim();
        const family = fontList.match(/^['"]?([^,'"]+)/)?.[1]?.trim();
        if (!family) throw new Error(`Missing computed font family for ${role}`);
        const probe = document.createElement('span');
        probe.textContent = 'WrzDJ 0123456789';
        probe.style.cssText = `position:fixed;left:-10000px;font:400 16px "${family}"`;
        document.body.append(probe);
        await document.fonts.load(`400 16px "${family}"`, probe.textContent);
        probe.remove();
      }),
    );
    await document.fonts.ready;
  });

  const fontState = await page.evaluate(() => {
    const roles = ['body', 'display', 'mono', 'grotesk'];
    return roles.map((role) => {
      const list = getComputedStyle(document.documentElement)
        .getPropertyValue(`--font-${role}`)
        .trim();
      const family = list.match(/^['"]?([^,'"]+)/)?.[1]?.trim() ?? '';
      const face = [...document.fonts].find(
        (candidate) => candidate.family.replaceAll('"', '') === family && candidate.status === 'loaded',
      );
      return {
        role,
        family,
        usesFallback: /fallback/i.test(family),
        loaded: Boolean(face),
        weightRange: face?.weight,
        appliedToBody: getComputedStyle(document.body).fontFamily.includes(family),
      };
    });
  });

  expect(fontState).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ role: 'body', usesFallback: false, loaded: true, weightRange: '100 1000', appliedToBody: true }),
      expect.objectContaining({ role: 'display', usesFallback: false, loaded: true, weightRange: '200 800' }),
      expect.objectContaining({ role: 'mono', usesFallback: false, loaded: true, weightRange: '100 800' }),
      expect.objectContaining({ role: 'grotesk', usesFallback: false, loaded: true, weightRange: '300 700' }),
    ]),
  );
  expect(fontRequests.length).toBeGreaterThanOrEqual(4);
  const applicationOrigin = new URL(page.url()).origin;
  expect(fontRequests.every((url) => new URL(url).origin === applicationOrigin)).toBe(true);
  expect(fontRequests.every((url) => new URL(url).pathname.includes('/_next/static/media/'))).toBe(true);
});
