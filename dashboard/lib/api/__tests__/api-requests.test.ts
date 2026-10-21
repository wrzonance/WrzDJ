import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '..';
import { mockFetch, setupApiClient } from './api-test-setup';

describe('ApiClient requests', () => {
  setupApiClient();
  describe('getPendingReview', () => {
        // #478: pending-review now returns a paginated envelope, not a bare array.
        const envelope = (overrides: Record<string, unknown> = {}) => ({
          requests: [],
          total: 0,
          limit: 100,
          offset: 0,
          sort: null,
          direction: null,
          ...overrides,
        });

        it('returns the paginated envelope with the true total', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () =>
              envelope({
                requests: [
                  {
                    id: 1,
                    song_title: 'S',
                    artist: 'A',
                    artwork_url: null,
                    vote_count: 5,
                    nickname: null,
                    created_at: '2026-04-21T12:00:00Z',
                    note: null,
                    status: 'new',
                  },
                ],
                total: 250,
              }),
          });

          const resp = await api.getPendingReview('ABC123');
          expect(resp.requests).toHaveLength(1);
          expect(resp.total).toBe(250);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/ABC123/pending-review');
        });

        it('omits sort/direction/limit/offset by default (Review order)', async () => {
          mockFetch.mockResolvedValueOnce({ ok: true, json: async () => envelope() });

          await api.getPendingReview('ABC123');

          const [url] = mockFetch.mock.calls[0];
          expect(url).not.toContain('sort=');
          expect(url).not.toContain('direction=');
          expect(url).not.toContain('limit=');
          expect(url).not.toContain('offset=');
        });

        it('appends sort + direction params when specified', async () => {
          mockFetch.mockResolvedValueOnce({ ok: true, json: async () => envelope() });

          await api.getPendingReview('ABC123', { sort: 'upvotes', direction: 'desc' });

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('sort=upvotes');
          expect(url).toContain('direction=desc');
        });

        it('appends limit + offset params, sending offset=0 even though falsy', async () => {
          mockFetch.mockResolvedValueOnce({ ok: true, json: async () => envelope() });

          await api.getPendingReview('ABC123', { limit: 200, offset: 0 });

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('limit=200');
          expect(url).toContain('offset=0');
        });
      });
  describe('updateRequestStatus', () => {
        it('updates request status', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ id: 1, status: 'accepted' }),
          });

          const result = await api.updateRequestStatus(1, 'accepted');
          expect(result.status).toBe('accepted');

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/requests/1');
          expect(options.method).toBe('PATCH');
          expect(JSON.parse(options.body)).toEqual({ status: 'accepted' });
        });
      });
  describe('deleteRequest', () => {
        it('deletes a request', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            status: 204,
            json: async () => undefined,
          });

          await api.deleteRequest(42);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/requests/42');
          expect(options.method).toBe('DELETE');
        });
      });
  describe('getCollectLeaderboard', () => {
        it('includes tab and paging params in the URL', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ requests: [], total: 0 }),
          });

          await api.getCollectLeaderboard('ABC123', 'all', { limit: 100, offset: 50 });

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('tab=all');
          expect(url).toContain('limit=100');
          expect(url).toContain('offset=50');
        });
      });
  describe('publicVoteRequest', () => {
        it('sends public vote without auth', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ vote_count: 6, has_voted: true, status: 'voted' }),
          });

          const result = await api.publicVoteRequest(10);
          expect(result.vote_count).toBe(6);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/requests/10/vote');
          expect(options.method).toBe('POST');
        });

        it('throws ApiError on failure', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: false,
            status: 429,
            json: async () => ({ detail: 'Rate limit exceeded' }),
          });

          await expect(api.publicVoteRequest(10)).rejects.toThrow('Rate limit exceeded');
        });
      });
  describe('publicUnvoteRequest', () => {
        it('removes a public vote with cookie credentials', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ vote_count: 4, has_voted: false, status: 'unvoted' }),
          });

          const result = await api.publicUnvoteRequest(10);
          expect(result).toMatchObject({ vote_count: 4, has_voted: false, status: 'unvoted' });

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/requests/10/vote');
          expect(options.method).toBe('DELETE');
          expect(options.credentials).toBe('include');
        });

        it('reverifies and retries a guest vote removal', async () => {
          mockFetch
            .mockResolvedValueOnce(new Response(
              JSON.stringify({ detail: { code: 'human_verification_required' } }),
              { status: 403, headers: { 'Content-Type': 'application/json' } },
            ))
            .mockResolvedValueOnce(new Response(
              JSON.stringify({ vote_count: 4, has_voted: false, status: 'unvoted' }),
              { status: 200, headers: { 'Content-Type': 'application/json' } },
            ));
          const reverify = vi.fn().mockResolvedValue(undefined);

          await expect(api.publicUnvoteRequest(10, reverify)).resolves.toMatchObject({
            vote_count: 4,
            has_voted: false,
            status: 'unvoted',
          });

          expect(reverify).toHaveBeenCalledTimes(1);
          expect(mockFetch).toHaveBeenCalledTimes(2);
          for (const [, options] of mockFetch.mock.calls) {
            expect(options.method).toBe('DELETE');
            expect(options.credentials).toBe('include');
          }
        });
      });
  describe('search', () => {
        it('encodes search query properly', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => [],
          });

          await api.search('test song & artist');

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('q=test%20song%20%26%20artist');
        });
      });
  describe('submitRequest', () => {
        it('sends song request data', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              id: 1,
              artist: 'Artist',
              song_title: 'Title',
              status: 'new',
            }),
          });

          const result = await api.submitRequest({
            eventCode: 'ABC123',
            artist: 'Artist',
            title: 'Title',
            note: 'Please play!',
          });

          expect(result.id).toBe(1);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/ABC123/requests');
          expect(options.method).toBe('POST');
          expect(options.credentials).toBe('include');

          const body = JSON.parse(options.body);
          expect(body.artist).toBe('Artist');
          expect(body.title).toBe('Title');
          expect(body.note).toBe('Please play!');
        });

        it('forwards the search-result ISRC into the request body (#552)', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ id: 2, artist: 'deadmau5', song_title: 'Strobe', status: 'new' }),
          });

          await api.submitRequest({
            eventCode: 'ABC123',
            artist: 'deadmau5',
            title: 'Strobe',
            metadata: { source: 'beatport', isrc: 'USXYZ1234567' },
          });

          const [, options] = mockFetch.mock.calls[0];
          expect(JSON.parse(options.body).isrc).toBe('USXYZ1234567');
        });
      });
  describe('kiosk session header', () => {
        afterEach(() => {
          api.setKioskSession(null);
        });

        it('eventSearch sends X-Kiosk-Session when a kiosk session is set', async () => {
          api.setKioskSession('kiosk-token-abc');
          mockFetch.mockResolvedValueOnce({ ok: true, json: async () => [] });

          await api.eventSearch('JOIN42', 'strobe');

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/JOIN42/search');
          expect(options.headers['X-Kiosk-Session']).toBe('kiosk-token-abc');
        });

        it('submitRequest sends X-Kiosk-Session when a kiosk session is set', async () => {
          api.setKioskSession('kiosk-token-abc');
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ id: 1, artist: 'A', song_title: 'T', status: 'new' }),
          });

          await api.submitRequest({ eventCode: 'JOIN42', artist: 'deadmau5', title: 'Strobe' });

          const [, options] = mockFetch.mock.calls[0];
          expect(options.headers['X-Kiosk-Session']).toBe('kiosk-token-abc');
        });

        it('omits X-Kiosk-Session for normal guest/DJ flows (no kiosk session)', async () => {
          mockFetch.mockResolvedValueOnce({ ok: true, json: async () => [] });

          await api.eventSearch('JOIN42', 'strobe');

          const [, options] = mockFetch.mock.calls[0];
          expect(options.headers['X-Kiosk-Session']).toBeUndefined();
        });
      });
  describe('getPlayHistory', () => {
        it('fetches play history with default parameters', async () => {
          const mockHistoryResponse = {
            items: [
              {
                id: 1,
                title: 'Test Song',
                artist: 'Test Artist',
                album: 'Test Album',
                album_art_url: 'https://example.com/art.jpg',
                spotify_uri: 'spotify:track:123',
                matched_request_id: null,
                source: 'stagelinq',
                started_at: '2024-01-01T12:00:00Z',
                ended_at: '2024-01-01T12:03:00Z',
                play_order: 1,
              },
            ],
            total: 1,
          };

          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => mockHistoryResponse,
          });

          const result = await api.getPlayHistory('ABC123');

          expect(result.items).toHaveLength(1);
          expect(result.items[0].title).toBe('Test Song');
          expect(result.items[0].source).toBe('stagelinq');
          expect(result.total).toBe(1);

          const [url] = mockFetch.mock.calls[0];
          // Regression for 43bd5021 (#800): limit=10 also matches limit=100.
          const requestUrl = new URL(url, 'http://test.local');
          expect(requestUrl.pathname).toMatch(/\/api\/public\/e\/ABC123\/history$/);
          expect(requestUrl.searchParams.get('limit')).toBe('100');
          expect(requestUrl.searchParams.get('offset')).toBe('0');
        });

        it('fetches play history with custom limit and offset', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ items: [], total: 0 }),
          });

          await api.getPlayHistory('ABC123', { limit: 5, offset: 10 });

          const [url] = mockFetch.mock.calls[0];
          const requestUrl = new URL(url, 'http://test.local');
          expect(requestUrl.searchParams.get('limit')).toBe('5');
          expect(requestUrl.searchParams.get('offset')).toBe('10');
        });

        it('returns items with matched_request_id when request was fulfilled', async () => {
          const mockHistoryResponse = {
            items: [
              {
                id: 1,
                title: 'Requested Song',
                artist: 'Requested Artist',
                album: null,
                album_art_url: null,
                spotify_uri: null,
                matched_request_id: 42,
                source: 'stagelinq',
                started_at: '2024-01-01T12:00:00Z',
                ended_at: null,
                play_order: 1,
              },
            ],
            total: 1,
          };

          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => mockHistoryResponse,
          });

          const result = await api.getPlayHistory('ABC123');

          expect(result.items[0].matched_request_id).toBe(42);
        });

        it('throws ApiError on failure', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: false,
            json: async () => ({ detail: 'Event not found' }),
          });

          await expect(api.getPlayHistory('INVALID')).rejects.toThrow('Event not found');
        });

        it('returns empty items array when no history exists', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ items: [], total: 0 }),
          });

          const result = await api.getPlayHistory('ABC123');

          expect(result.items).toHaveLength(0);
          expect(result.total).toBe(0);
        });
      });
  describe('exportPlayHistoryCsv', () => {
        it('downloads play history CSV file', async () => {

          const mockBlob = new Blob(['csv,content'], { type: 'text/csv' });
          mockFetch.mockResolvedValueOnce({
            ok: true,
            blob: async () => mockBlob,
            headers: new Headers({
              'Content-Disposition': 'attachment; filename="ABC123_play_history_20260205.csv"',
              'X-Export-Truncated': 'true',
            }),
          });

          // Mock URL and document APIs
          const mockUrl = 'blob:http://localhost/abc123';
          const createObjectURLSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue(mockUrl);
          const revokeObjectURLSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});

          const mockAnchor = {
            href: '',
            download: '',
            click: vi.fn(),
          };
          const createElementSpy = vi.spyOn(document, 'createElement').mockReturnValue(mockAnchor as unknown as HTMLElement);

          const truncated = await api.exportPlayHistoryCsv('ABC123');
          expect(truncated).toBe(true);

          // Correct endpoint was fetched
          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/ABC123/export/play-history/csv');

          // Blob was prepared for download
          expect(createObjectURLSpy).toHaveBeenCalledWith(mockBlob);

          // Temp object URL was cleaned up
          expect(revokeObjectURLSpy).toHaveBeenCalledWith(mockUrl);

          createObjectURLSpy.mockRestore();
          revokeObjectURLSpy.mockRestore();
          createElementSpy.mockRestore();
        });

        it('throws ApiError on failure', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: false,
            json: async () => ({ detail: 'Event not found' }),
          });

          await expect(api.exportPlayHistoryCsv('INVALID')).rejects.toThrow('Event not found');
        });

        it('includes auth token in request', async () => {

          mockFetch.mockResolvedValueOnce({
            ok: true,
            blob: async () => new Blob(['csv'], { type: 'text/csv' }),
            headers: new Headers({
              'Content-Disposition': 'attachment; filename="test.csv"',
            }),
          });

          // Mock DOM APIs
          vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test');
          vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
          vi.spyOn(document, 'createElement').mockReturnValue({
            href: '',
            download: '',
            click: vi.fn(),
          } as unknown as HTMLElement);

          await api.exportPlayHistoryCsv('ABC123');

          const [, options] = mockFetch.mock.calls[0];
          expect(options.headers.get('Authorization')).toBeNull();
          expect(options.credentials).toBe('include');
        });
      });
  describe('getRequests', () => {
        // #478: the endpoint now returns a paginated envelope, not a bare array.
        const envelope = (overrides: Record<string, unknown> = {}) => ({
          requests: [],
          total: 0,
          limit: 100,
          offset: 0,
          sort: 'date_requested',
          direction: 'desc',
          ...overrides,
        });

        it('returns the paginated envelope for an event', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => envelope({
              requests: [
                { id: 1, artist: 'A', song_title: 'S', status: 'new' },
                { id: 2, artist: 'B', song_title: 'T', status: 'accepted' },
              ],
              total: 2,
            }),
          });

          const resp = await api.getRequests('ABC123');
          expect(resp.requests).toHaveLength(2);
          expect(resp.total).toBe(2);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/ABC123/requests');
          expect(url).not.toContain('status=');
        });

        it('filters requests by status', async () => {
          mockFetch.mockResolvedValueOnce({ ok: true, json: async () => envelope() });

          await api.getRequests('ABC123', { status: 'new' });

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('status=new');
        });

        it('appends sort + direction params when specified', async () => {
          mockFetch.mockResolvedValueOnce({ ok: true, json: async () => envelope() });

          await api.getRequests('ABC123', { sort: 'best_match', direction: 'desc' });

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('sort=best_match');
          expect(url).toContain('direction=desc');
        });

        it('appends limit + offset params when specified', async () => {
          mockFetch.mockResolvedValueOnce({ ok: true, json: async () => envelope() });

          await api.getRequests('ABC123', { limit: 200, offset: 0 });

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('limit=200');
          expect(url).toContain('offset=0');
        });

        it('sends offset=0 even though it is falsy (growing-window contract)', async () => {
          mockFetch.mockResolvedValueOnce({ ok: true, json: async () => envelope() });

          await api.getRequests('ABC123', { limit: 100, offset: 0 });

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('offset=0');
        });

        it('omits sort/direction/limit/offset by default', async () => {
          mockFetch.mockResolvedValueOnce({ ok: true, json: async () => envelope() });

          await api.getRequests('ABC123');

          const [url] = mockFetch.mock.calls[0];
          expect(url).not.toContain('sort=');
          expect(url).not.toContain('direction=');
          expect(url).not.toContain('limit=');
          expect(url).not.toContain('offset=');
        });
      });
  describe('acceptAllRequests', () => {
        it('accepts all pending requests', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ status: 'ok', accepted_count: 5 }),
          });

          const result = await api.acceptAllRequests('ABC123');
          expect(result.accepted_count).toBe(5);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/ABC123/requests/accept-all');
          expect(options.method).toBe('POST');
        });
      });
  describe('eventSearch', () => {
        it('searches via event code with cookie credentials', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => [{ title: 'Found Song', artist: 'Found Artist' }],
          });

          const results = await api.eventSearch('EVT001', 'query here');
          expect(results).toHaveLength(1);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/EVT001/search');
          expect(url).toContain('q=query%20here');
        });
      });
  describe('checkHasRequested', () => {
        it('checks if client has already requested', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ has_requested: true, request_id: 7 }),
          });

          const result = await api.checkHasRequested('ABC123');
          expect(result.has_requested).toBe(true);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/public/events/ABC123/has-requested');
        });
      });
  describe('getPublicRequests', () => {
        it('fetches public request list', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              requests: [{ id: 1, artist: 'A', title: 'S', vote_count: 3 }],
              event_name: 'Party',
              requests_open: true,
            }),
          });

          const result = await api.getPublicRequests('ABC123');
          expect(result.requests).toHaveLength(1);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/public/events/ABC123/requests');
        });

        it('appends limit and offset when provided', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ requests: [], now_playing: null, total: 0 }),
          });

          await api.getPublicRequests('ABC123', { limit: 100, offset: 200 });

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('limit=100');
          expect(url).toContain('offset=200');
        });

        it('omits the query string when no paging args are given', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ requests: [], now_playing: null, total: 0 }),
          });

          await api.getPublicRequests('ABC123');

          const [url] = mockFetch.mock.calls[0];
          expect(url).not.toContain('?');
        });
      });
  describe('voteRequest', () => {
        it('sends authenticated vote', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ vote_count: 5, has_voted: true, status: 'voted' }),
          });

          const result = await api.voteRequest(10);
          expect(result.vote_count).toBe(5);
          expect(result.has_voted).toBe(true);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/requests/10/vote');
          expect(options.method).toBe('POST');
        });
      });
  describe('unvoteRequest', () => {
        it('removes authenticated vote', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ vote_count: 4, has_voted: false, status: 'unvoted' }),
          });

          const result = await api.unvoteRequest(10);
          expect(result.vote_count).toBe(4);
          expect(result.has_voted).toBe(false);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/requests/10/vote');
          expect(options.method).toBe('DELETE');
        });
      });
  describe('setCollectProfile — nickname collision', () => {
        afterEach(() => vi.restoreAllMocks());

        it('throws NicknameConflictError with claimed=true on 409', async () => {
          vi.spyOn(global, 'fetch').mockResolvedValueOnce(
            new Response(
              JSON.stringify({ detail: { code: 'nickname_taken', claimed: true } }),
              { status: 409, headers: { 'Content-Type': 'application/json' } },
            ),
          );
          await expect(api.setCollectProfile('EVT01', { nickname: 'Alex' })).rejects.toMatchObject({
            name: 'NicknameConflictError',
            claimed: true,
          });
        });

        it('throws NicknameConflictError with claimed=false on 409', async () => {
          vi.spyOn(global, 'fetch').mockResolvedValueOnce(
            new Response(
              JSON.stringify({ detail: { code: 'nickname_taken', claimed: false } }),
              { status: 409, headers: { 'Content-Type': 'application/json' } },
            ),
          );
          await expect(api.setCollectProfile('EVT01', { nickname: 'Alex' })).rejects.toMatchObject({
            name: 'NicknameConflictError',
            claimed: false,
          });
        });

        // NicknameGate always passes reverify; the 409 must survive withHumanRetry
        // so a taken name opens the collision screen instead of "Request failed".
        it('throws NicknameConflictError on 409 when called with reverify', async () => {
          vi.spyOn(global, 'fetch').mockResolvedValueOnce(
            new Response(
              JSON.stringify({ detail: { code: 'nickname_taken', claimed: true } }),
              { status: 409, headers: { 'Content-Type': 'application/json' } },
            ),
          );
          const reverify = vi.fn();
          await expect(
            api.setCollectProfile('EVT01', { nickname: 'Alex' }, reverify),
          ).rejects.toMatchObject({ name: 'NicknameConflictError', claimed: true });
          expect(reverify).not.toHaveBeenCalled();
        });

        // #853: the server's real 422 for a filtered name reaches NicknameGate as
        // the validator's own message, so the guest knows to pick another name.
        it('surfaces the nickname validator message from a real 422 body', async () => {
          vi.spyOn(global, 'fetch').mockResolvedValueOnce(
            new Response(
              JSON.stringify({
                detail: [
                  {
                    type: 'value_error',
                    loc: ['body', 'nickname'],
                    msg: 'Value error, Please choose a different name',
                    input: 'Rude',
                  },
                ],
              }),
              { status: 422, headers: { 'Content-Type': 'application/json' } },
            ),
          );
          await expect(
            api.setCollectProfile('EVT01', { nickname: 'Rude' }, vi.fn()),
          ).rejects.toMatchObject({ status: 422, message: 'Please choose a different name' });
        });
      });
});
