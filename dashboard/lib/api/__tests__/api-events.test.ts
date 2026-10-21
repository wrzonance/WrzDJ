import { describe, it, expect, vi } from 'vitest';
import { api } from '..';
import { mockFetch, setupApiClient } from './api-test-setup';

describe('ApiClient events', () => {
  setupApiClient();
  describe('getEvents', () => {
        it('fetches events with the cookie session and no bearer header', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => [{ id: 1, code: 'ABC123', name: 'Test Event' }],
          });

          const events = await api.getEvents();

          expect(events).toHaveLength(1);
          expect(events[0].code).toBe('ABC123');

          const [, options] = mockFetch.mock.calls[0];
          expect(options.headers.get('Authorization')).toBeNull();
          expect(options.credentials).toBe('include');
        });
      });
  describe('deleteEvent', () => {
        it('sends DELETE request with cookie credentials and no bearer header', async () => {
          mockFetch.mockResolvedValueOnce({ ok: true });

          await api.deleteEvent('ABC123');

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/ABC123');
          expect(options.method).toBe('DELETE');
          expect(options.headers.get('Authorization')).toBeNull();
          expect(options.credentials).toBe('include');
        });

        it('throws on failure with detail message', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: false,
            json: async () => ({ detail: 'Event not found' }),
          });

          await expect(api.deleteEvent('INVALID')).rejects.toThrow('Event not found');
        });

        it('throws generic message when json parsing fails', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: false,
            json: async () => { throw new Error('not json'); },
          });

          await expect(api.deleteEvent('INVALID')).rejects.toThrow('Request failed');
        });
      });
  describe('getNowPlaying', () => {
        it('fetches now playing info for an event', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              title: 'Strobe',
              artist: 'deadmau5',
              album: 'For Lack of a Better Name',
              album_art_url: 'https://example.com/art.jpg',
            }),
          });

          const result = await api.getNowPlaying('ABC123');

          expect(result).not.toBeNull();
          expect(result!.title).toBe('Strobe');
          expect(result!.artist).toBe('deadmau5');

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/public/e/ABC123/nowplaying');
        });

        it('returns null when no track is playing', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => null,
          });

          const result = await api.getNowPlaying('ABC123');
          expect(result).toBeNull();

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/public/e/ABC123/nowplaying');
        });

        it('throws ApiError for 404', async () => {
          mockFetch.mockResolvedValueOnce({ ok: false, status: 404 });

          await expect(api.getNowPlaying('INVALID')).rejects.toThrow('Event not found');
        });

        it('throws ApiError for 410', async () => {
          mockFetch.mockResolvedValueOnce({ ok: false, status: 410 });

          await expect(api.getNowPlaying('GONE')).rejects.toThrow('Event not found');
        });

        it('throws ApiError for unexpected HTTP failures', async () => {
          mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });

          await expect(api.getNowPlaying('ABC123')).rejects.toMatchObject({
            name: 'ApiError',
            status: 500,
          });
        });
      });
  describe('exportEventCsv', () => {
        it('downloads event CSV with correct URL', async () => {

          const mockBlob = new Blob(['csv,content'], { type: 'text/csv' });
          mockFetch.mockResolvedValueOnce({
            ok: true,
            blob: async () => mockBlob,
            headers: new Headers({
              'Content-Disposition': 'attachment; filename="ABC123.csv"',
              'X-Export-Truncated': 'false',
            }),
          });

          vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test');
          vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
          vi.spyOn(document, 'createElement').mockReturnValue({
            href: '',
            download: '',
            click: vi.fn(),
          } as unknown as HTMLElement);

          const truncated = await api.exportEventCsv('ABC123');
          expect(truncated).toBe(false);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/ABC123/export/csv');
        });

        it('throws ApiError on failure', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: false,
            status: 403,
            json: async () => ({ detail: 'Forbidden' }),
          });

          await expect(api.exportEventCsv('ABC123')).rejects.toThrow('Forbidden');
        });

        it('returns unknown when the truncation header is missing', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            blob: async () => new Blob(['csv,content'], { type: 'text/csv' }),
            headers: new Headers({
              'Content-Disposition': 'attachment; filename="ABC123.csv"',
            }),
          });

          vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test');
          vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
          vi.spyOn(document, 'createElement').mockReturnValue({
            href: '',
            download: '',
            click: vi.fn(),
          } as unknown as HTMLElement);

          await expect(api.exportEventCsv('ABC123')).resolves.toBeNull();
        });
      });
  describe('Kiosk Pairing API', () => {
        it('creates a kiosk pairing session', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              pair_code: 'ABC234',
              session_token: 'a'.repeat(64),
              expires_at: '2026-02-20T12:05:00Z',
            }),
          });

          const result = await api.createKioskPairing('test-nonce-xyz');
          expect(result.pair_code).toBe('ABC234');
          expect(result.session_token).toHaveLength(64);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/public/kiosk/pair');
          expect(options.method).toBe('POST');
          expect(options.headers['X-Pair-Nonce']).toBe('test-nonce-xyz');
        });

        it('polls pairing status', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              status: 'pairing',
              event_code: null,
              event_name: null,
            }),
          });

          const result = await api.getKioskPairStatus('ABC234');
          expect(result.status).toBe('pairing');

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/public/kiosk/pair/ABC234/status');
        });

        it('polls kiosk session assignment via X-Kiosk-Session header', async () => {
          const token = 'b'.repeat(64);
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              status: 'active',
              event_code: 'EVT001',
              event_name: 'Friday Night',
            }),
          });

          const result = await api.getKioskAssignment(token);
          expect(result.status).toBe('active');
          expect(result.event_code).toBe('EVT001');

          const [url, options] = mockFetch.mock.calls[0];
          // Token must NOT appear in the URL (security: prevents log leakage)
          expect(url).toContain('/api/public/kiosk/session/assignment');
          expect(url).not.toContain(token);
          // Token sent in header instead
          expect(options.headers['X-Kiosk-Session']).toBe(token);
        });

        it('completes kiosk pairing', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              id: 1,
              name: null,
              event_code: 'EVT001',
              event_name: 'Friday Night',
              status: 'active',
              paired_at: '2026-02-20T12:01:00Z',
              last_seen_at: null,
            }),
          });

          const result = await api.completeKioskPairing('ABC234', 'EVT001');
          expect(result.status).toBe('active');
          expect(result.event_code).toBe('EVT001');

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/kiosk/pair/ABC234/complete');
          expect(options.method).toBe('POST');
          expect(JSON.parse(options.body)).toEqual({ event_code: 'EVT001' });
        });

        it('lists my kiosks', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => [
              { id: 1, name: 'Bar Kiosk', event_code: 'EVT001', status: 'active' },
            ],
          });

          const result = await api.getMyKiosks();
          expect(result).toHaveLength(1);
          expect(result[0].name).toBe('Bar Kiosk');

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/kiosk/mine');
        });

        it('assigns kiosk to event', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ id: 1, event_code: 'EVT002', status: 'active' }),
          });

          const result = await api.assignKiosk(1, 'EVT002');
          expect(result.event_code).toBe('EVT002');

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/kiosk/1/assign');
          expect(options.method).toBe('PATCH');
        });

        it('renames a kiosk', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ id: 1, name: 'Stage Left' }),
          });

          const result = await api.renameKiosk(1, 'Stage Left');
          expect(result.name).toBe('Stage Left');

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/kiosk/1');
          expect(options.method).toBe('PATCH');
          expect(JSON.parse(options.body)).toEqual({ name: 'Stage Left' });
        });

        it('deletes a kiosk', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            status: 204,
            json: async () => undefined,
          });

          await api.deleteKiosk(1);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/kiosk/1');
          expect(options.method).toBe('DELETE');
        });
      });
  describe('createEvent', () => {
        it('creates event with name and default expiry', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ id: 1, code: 'NEW123', name: 'Party Night' }),
          });

          const event = await api.createEvent('Party Night');

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events');
          expect(options.method).toBe('POST');
          const body = JSON.parse(options.body);
          expect(body.name).toBe('Party Night');
          expect(body.expires_hours).toBe(6);
          expect(event.code).toBe('NEW123');
        });

        it('creates event with custom expiry', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ id: 2, code: 'ABC456', name: 'All-Nighter' }),
          });

          await api.createEvent('All-Nighter', 12);

          const body = JSON.parse(mockFetch.mock.calls[0][1].body);
          expect(body.expires_hours).toBe(12);
        });
      });
  describe('updateEvent', () => {
        it('patches event with new name', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ id: 1, code: 'ABC123', name: 'New Name' }),
          });

          const result = await api.updateEvent('ABC123', { name: 'New Name' });
          expect(result.name).toBe('New Name');

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/ABC123');
          expect(options.method).toBe('PATCH');
        });
      });
  describe('getArchivedEvents', () => {
        it('fetches archived events', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => [
              { code: 'OLD123', name: 'Old Event', request_count: 42, created_at: '2026-01-01' },
            ],
          });

          const events = await api.getArchivedEvents();
          expect(events).toHaveLength(1);
          expect(events[0].request_count).toBe(42);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/archived');
        });
      });
  describe('refreshRequestMetadata', () => {
        it('triggers metadata refresh for a request', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ id: 5, artist: 'Artist', song_title: 'Song', bpm: 128 }),
          });

          const result = await api.refreshRequestMetadata(5);
          expect(result.bpm).toBe(128);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/requests/5/refresh-metadata');
          expect(options.method).toBe('POST');
        });
      });
  describe('getKioskDisplay', () => {
        const kioskDisplayBody = {
          event: { code: 'FRI001', name: 'Friday Night' },
          qr_join_url: 'https://example.com/join/FRI001',
          accepted_queue: [],
          accepted_queue_total: 0,
          now_playing: null,
          now_playing_hidden: false,
          requests_open: true,
          kiosk_display_only: false,
          updated_at: '2026-01-01T00:00:00Z',
          banner_url: null,
          banner_kiosk_url: null,
          banner_colors: null,
        };

        it('fetches kiosk display data', async () => {
          mockFetch.mockResolvedValueOnce({ ok: true, json: async () => kioskDisplayBody });

          const result = await api.getKioskDisplay('FRI001');
          expect(result.event.name).toBe('Friday Night');
          expect(result.accepted_queue_total).toBe(0);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/public/events/FRI001/display');
          expect(url).not.toContain('?');
        });

        it('appends limit and offset when provided', async () => {
          mockFetch.mockResolvedValueOnce({ ok: true, json: async () => kioskDisplayBody });

          await api.getKioskDisplay('FRI001', { limit: 200, offset: 100 });

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('limit=200');
          expect(url).toContain('offset=100');
        });
      });
  describe('setNowPlayingVisibility', () => {
        it('sets now playing hidden', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ now_playing_hidden: true, now_playing_auto_hide_minutes: 30 }),
          });

          const result = await api.setNowPlayingVisibility('ABC123', true);
          expect(result.now_playing_hidden).toBe(true);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/ABC123/display-settings');
          expect(options.method).toBe('PATCH');
          expect(JSON.parse(options.body)).toEqual({ now_playing_hidden: true });
        });

        it('sets visibility with auto-hide minutes', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ now_playing_hidden: false, now_playing_auto_hide_minutes: 15 }),
          });

          await api.setNowPlayingVisibility('ABC123', false, 15);

          const body = JSON.parse(mockFetch.mock.calls[0][1].body);
          expect(body.now_playing_hidden).toBe(false);
          expect(body.now_playing_auto_hide_minutes).toBe(15);
        });
      });
  describe('setAutoHideMinutes', () => {
        it('updates auto-hide timeout', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ now_playing_auto_hide_minutes: 45 }),
          });

          const result = await api.setAutoHideMinutes('ABC123', 45);
          expect(result.now_playing_auto_hide_minutes).toBe(45);

          const body = JSON.parse(mockFetch.mock.calls[0][1].body);
          expect(body).toEqual({ now_playing_auto_hide_minutes: 45 });
        });
      });
  describe('getDisplaySettings', () => {
        it('fetches display settings', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              now_playing_hidden: false,
              now_playing_auto_hide_minutes: 30,
              requests_open: true,
              kiosk_display_only: false,
            }),
          });

          const result = await api.getDisplaySettings('ABC123');
          expect(result.requests_open).toBe(true);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/ABC123/display-settings');
        });
      });
  describe('setRequestsOpen', () => {
        it('closes requests', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ requests_open: false }),
          });

          const result = await api.setRequestsOpen('ABC123', false);
          expect(result.requests_open).toBe(false);

          const body = JSON.parse(mockFetch.mock.calls[0][1].body);
          expect(body).toEqual({ requests_open: false });
        });
      });
  describe('setKioskDisplayOnly', () => {
        it('enables kiosk display-only mode', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ kiosk_display_only: true }),
          });

          const result = await api.setKioskDisplayOnly('ABC123', true);
          expect(result.kiosk_display_only).toBe(true);

          const body = JSON.parse(mockFetch.mock.calls[0][1].body);
          expect(body).toEqual({ kiosk_display_only: true });
        });
      });
});
