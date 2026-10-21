import { expect, test, type Page, type Route } from '@playwright/test';

const EVENT_CODE = 'E2ESEARCH';
const ARTWORK =
  'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="48" height="48"/%3E';

interface SearchFixture {
  onSearch: (query: string, route: Route) => Promise<void>;
  submittedRequests: Record<string, unknown>[];
  searchedQueries: string[];
  diagnostics: string[];
}

function result(title: string, options: { source?: string; bpm?: number; key?: string } = {}) {
  return {
    title,
    artist: `${title} Artist`,
    album: `${title} Album`,
    album_art: ARTWORK,
    bpm: options.bpm ?? 124,
    key: options.key ?? '8A',
    genre: 'House',
    isrc: 'USAAA2600001',
    popularity: 72,
    preview_url: null,
    source: options.source ?? 'spotify',
    spotify_id: `id-${title.toLowerCase().replaceAll(' ', '-')}`,
    url: `https://example.invalid/tracks/${encodeURIComponent(title)}`,
  };
}

async function installGuestSearchFixture(
  page: Page,
  onSearch: SearchFixture['onSearch'],
): Promise<SearchFixture> {
  const fixture: SearchFixture = { onSearch, submittedRequests: [], searchedQueries: [], diagnostics: [] };
  page.on('pageerror', (error) => fixture.diagnostics.push(`pageerror ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error') fixture.diagnostics.push(`console ${message.text()}`);
  });

  // Allow only local app assets and the routed API fixture; third-party
  // providers, analytics, and accidentally unhandled remote calls stay offline.
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (['127.0.0.1', 'localhost', '::1'].includes(url.hostname)) {
      await route.continue();
      return;
    }
    await route.abort();
  });

  // Keep this browser flow hermetic: every API request is answered locally and
  // unknown API paths fail instead of reaching a configured or live service.
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    fixture.diagnostics.push(`intercepted ${request.method()} ${path}`);

    if (path === '/api/public/guest/identify') {
      await route.fulfill({ json: { guest_id: 101, action: 'create', reconcile_hint: false } });
      return;
    }
    if (path === '/api/public/guest/verify-status') {
      await route.fulfill({ json: { verified: true, expires_in: 3600 } });
      return;
    }
    if (path === `/api/public/collect/${EVENT_CODE}/join-config`) {
      await route.fulfill({ json: { frictionless_join: true } });
      return;
    }
    if (path === `/api/public/collect/${EVENT_CODE}/guest/ensure-name`) {
      await route.fulfill({ json: { nickname: 'GuestDJ', auto_generated: true } });
      return;
    }
    if (path === `/api/public/events/${EVENT_CODE}`) {
      await route.fulfill({
        json: {
          name: 'Search Fixture Event',
          phase: 'live',
          requests_open: true,
          collection_code: EVENT_CODE,
          frictionless_join: true,
          submission_cap_per_guest: 5,
          banner_url: null,
          banner_colors: null,
        },
      });
      return;
    }
    if (path === `/api/public/events/${EVENT_CODE}/has-requested`) {
      await route.fulfill({ json: { has_requested: false } });
      return;
    }
    if (path === `/api/public/events/${EVENT_CODE}/requests` && request.method() === 'GET') {
      await route.fulfill({
        json: { requests: [], now_playing: null, total: 0, event: { name: 'Search Fixture Event' } },
      });
      return;
    }
    if (path === `/api/public/events/${EVENT_CODE}/my-requests`) {
      await route.fulfill({ json: { requests: [] } });
      return;
    }
    if (path === `/api/public/collect/${EVENT_CODE}/profile`) {
      await route.fulfill({
        json: { email_verified: false, nickname: 'GuestDJ', submission_cap: 5, submission_count: 0 },
      });
      return;
    }
    if (path === '/api/auth/settings') {
      await route.fulfill({ json: { registration_enabled: false, turnstile_site_key: '' } });
      return;
    }
    if (path === `/api/events/${EVENT_CODE}/search` && request.method() === 'GET') {
      const query = url.searchParams.get('q') ?? '';
      fixture.searchedQueries.push(query);
      await fixture.onSearch(query, route);
      return;
    }
    if (path === `/api/search` && request.method() === 'GET') {
      await route.fulfill({ status: 503, json: { detail: 'Fixture fallback search unavailable' } });
      return;
    }
    if (path === `/api/events/${EVENT_CODE}/requests` && request.method() === 'POST') {
      fixture.submittedRequests.push(request.postDataJSON() as Record<string, unknown>);
      await route.fulfill({ json: { id: 301, is_duplicate: false, vote_count: 1 } });
      return;
    }

    await route.fulfill({ status: 404, json: { detail: `Unmatched E2E API route: ${request.method()} ${path}` } });
  });

  // The verify-status fixture should prevent Turnstile from loading. Block the
  // provider script defensively so this test can never contact Cloudflare.
  await page.route('https://challenges.cloudflare.com/**', (route) => route.abort());
  return fixture;
}

async function openSearchSheet(page: Page, fixture: SearchFixture) {
  await page.goto(`/join/${EVENT_CODE}`);
  await expect(
    page.getByPlaceholder('Search for a song or artist...'),
    `Guest gate did not open; intercepted API calls: ${fixture.diagnostics.join(', ') || '(none)'}`,
  ).toBeVisible();
}

async function searchFor(page: Page, query: string) {
  await page.getByPlaceholder('Search for a song or artist...').fill(query);
  await page.getByRole('button', { name: 'Search' }).click();
}

test.describe('Guest search workflow', () => {
  test.beforeEach(({ baseURL }) => {
    const hostname = new URL(baseURL ?? '').hostname;
    expect(['127.0.0.1', 'localhost', '::1']).toContain(hostname);
  });

  test('renders the event search result with its artwork and provider identity', async ({ page }) => {
    const fixture = await installGuestSearchFixture(page, async (_query, route) => {
      await route.fulfill({ json: [result('Signal Bloom', { source: 'beatport' })] });
    });

    await openSearchSheet(page, fixture);
    await searchFor(page, 'signal bloom');

    const item = page.getByRole('button', { name: /Signal Bloom Signal Bloom Artist/ });
    await expect(item).toBeVisible();
    await expect(item.getByRole('img', { name: 'Signal Bloom Album' })).toHaveAttribute('src', ARTWORK);
    await expect(item.locator('[title="Beatport"]')).toBeVisible();
    expect(fixture.searchedQueries).toEqual(['signal bloom']);
  });

  test('a failed search can be retried and replaces the error with matching results', async ({ page }) => {
    const fixture = await installGuestSearchFixture(page, async (query, route) => {
      if (query === 'broken query') {
        await route.fulfill({ status: 503, json: { detail: 'Fixture search unavailable' } });
        return;
      }
      await route.fulfill({ json: [result('Recovered Signal')] });
    });

    await openSearchSheet(page, fixture);
    await searchFor(page, 'broken query');
    const searchAlert = page.locator('.gst-request-sheet [role="alert"]');
    await expect(searchAlert).toHaveText('Song search is unavailable. Please try again.');

    await searchFor(page, 'recovered signal');
    await expect(searchAlert).toHaveCount(0);
    await expect(page.getByRole('button', { name: /Recovered Signal Recovered Signal Artist/ })).toBeVisible();
    expect(fixture.searchedQueries).toEqual(['broken query', 'recovered signal']);
  });

  test('consecutive queries show only results returned for the latest query', async ({ page }) => {
    // Regression for baseline 57cfcdc6867f: a stale first-query result cannot satisfy the second search.
    let releaseLatestResponse!: () => void;
    const latestResponse = new Promise<void>((resolve) => { releaseLatestResponse = resolve; });
    let latestRequestSeen!: () => void;
    const latestSearchSeen = new Promise<void>((resolve) => { latestRequestSeen = resolve; });
    const fixture = await installGuestSearchFixture(page, async (query, route) => {
      if (query === 'first query') {
        await route.fulfill({ json: [result('First Query Result')] });
        return;
      }
      latestRequestSeen();
      await latestResponse;
      await route.fulfill({ json: [result('Latest Query Result')] });
    });

    await openSearchSheet(page, fixture);
    await searchFor(page, 'first query');
    const firstResult = page.getByRole('button', { name: /First Query Result First Query Result Artist/ });
    await expect(firstResult).toBeVisible();

    await searchFor(page, 'latest query');
    await latestSearchSeen;
    await expect(firstResult).toHaveCount(0);
    await expect(page.getByRole('button', { name: '…' })).toBeVisible();

    releaseLatestResponse();
    await expect(page.getByRole('button', { name: /Latest Query Result Latest Query Result Artist/ })).toBeVisible();
    await expect(firstResult).toHaveCount(0);
    expect(fixture.searchedQueries).toEqual(['first query', 'latest query']);
  });

  test('selecting and submitting a result preserves its metadata in the request', async ({ page }) => {
    const fixture = await installGuestSearchFixture(page, async (_query, route) => {
      await route.fulfill({ json: [result('Queued Result', { bpm: 127, key: '9A' })] });
    });

    await openSearchSheet(page, fixture);
    await searchFor(page, 'queued result');
    await page.getByRole('button', { name: /Queued Result Queued Result Artist/ }).click();
    await expect(page.getByText('Confirm Request')).toBeVisible();
    await page.getByPlaceholder("e.g., It's my birthday!").fill('Play this next');
    await page.getByRole('button', { name: 'Submit Request' }).click();

    await expect(page.getByText('Request Submitted!')).toBeVisible();
    expect(fixture.submittedRequests).toEqual([
      expect.objectContaining({
        title: 'Queued Result',
        artist: 'Queued Result Artist',
        note: 'Play this next',
        raw_search_query: 'queued result',
        source: 'spotify',
        bpm: 127,
        musical_key: '9A',
        nickname: 'GuestDJ',
      }),
    ]);
  });
});
