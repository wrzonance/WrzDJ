import { describe, it, expect, vi, beforeEach } from 'vitest';
import { api, ApiError } from '..';
import { mockFetch, setupApiClient } from './api-test-setup';

describe('ApiClient integrations', () => {
  setupApiClient();
  describe('Beatport API', () => {
        beforeEach(() => {
        });

        it('fetches Beatport status', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ linked: true, expires_at: '2026-03-01T00:00:00Z' }),
          });

          const status = await api.getBeatportStatus();
          expect(status.linked).toBe(true);
          expect(status.expires_at).toBe('2026-03-01T00:00:00Z');

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/beatport/status');
        });

        it('logs in to Beatport with username and password', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ status: 'ok', message: 'Beatport account linked' }),
          });

          const result = await api.loginBeatport('myuser', 'mypass');
          expect(result.status).toBe('ok');

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/beatport/auth/login');
          expect(options.method).toBe('POST');
          const body = JSON.parse(options.body);
          expect(body.username).toBe('myuser');
          expect(body.password).toBe('mypass');
        });

        it('disconnects Beatport', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ status: 'ok', message: 'Beatport disconnected' }),
          });

          const result = await api.disconnectBeatport();
          expect(result.status).toBe('ok');

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/beatport/disconnect');
          expect(options.method).toBe('POST');
        });

        it('fetches Beatport event settings', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ beatport_sync_enabled: true }),
          });

          const settings = await api.getBeatportEventSettings(42);
          expect(settings.beatport_sync_enabled).toBe(true);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/beatport/events/42/settings');
        });

        it('updates Beatport event settings', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ beatport_sync_enabled: false }),
          });

          const settings = await api.updateBeatportEventSettings(42, {
            beatport_sync_enabled: false,
          });
          expect(settings.beatport_sync_enabled).toBe(false);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/beatport/events/42/settings');
          expect(options.method).toBe('PUT');
          expect(JSON.parse(options.body)).toEqual({ beatport_sync_enabled: false });
        });

        it('searches Beatport tracks', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => [
              {
                track_id: '12345',
                title: 'Strobe',
                artist: 'deadmau5',
                mix_name: 'Original Mix',
                label: 'mau5trap',
                genre: 'Progressive House',
                bpm: 128,
                key: 'F Minor',
                duration_seconds: 630,
                cover_url: null,
                beatport_url: 'https://beatport.com/track/strobe/12345',
                release_date: '2009-09-22',
              },
            ],
          });

          const results = await api.searchBeatport('strobe deadmau5');
          expect(results).toHaveLength(1);
          expect(results[0].title).toBe('Strobe');
          expect(results[0].mix_name).toBe('Original Mix');
          expect(results[0].bpm).toBe(128);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/beatport/search');
          expect(url).toContain('q=strobe%20deadmau5');
        });

        it('links a Beatport track to a request', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ status: 'linked' }),
          });

          const result = await api.linkBeatportTrack(7, 'bp-track-99');
          expect(result.status).toBe('linked');

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/beatport/requests/7/link');
          expect(options.method).toBe('POST');
          expect(JSON.parse(options.body)).toEqual({ beatport_track_id: 'bp-track-99' });
        });
      });
  describe('Tidal API', () => {
        beforeEach(() => {
        });

        it('fetches Tidal status', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ linked: true, user_id: '12345', quality: 'HI_RES' }),
          });

          const status = await api.getTidalStatus();
          expect(status.linked).toBe(true);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/tidal/status');
        });

        it('starts Tidal auth flow', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              verification_url: 'https://link.tidal.com/ABCDE',
              user_code: 'ABCDE',
              message: 'Visit link',
            }),
          });

          const result = await api.startTidalAuth();
          expect(result.verification_url).toContain('tidal.com');
          expect(result.user_code).toBe('ABCDE');

          const [, options] = mockFetch.mock.calls[0];
          expect(options.method).toBe('POST');
        });

        it('checks Tidal auth status - pending', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ complete: false, pending: true }),
          });

          const result = await api.checkTidalAuth();
          expect(result.complete).toBe(false);
          expect(result.pending).toBe(true);
        });

        it('checks Tidal auth status - complete', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ complete: true, user_id: '12345' }),
          });

          const result = await api.checkTidalAuth();
          expect(result.complete).toBe(true);
          expect(result.user_id).toBe('12345');
        });

        it('cancels Tidal auth', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ status: 'ok', message: 'Auth cancelled' }),
          });

          const result = await api.cancelTidalAuth();
          expect(result.status).toBe('ok');

          const [, options] = mockFetch.mock.calls[0];
          expect(options.method).toBe('POST');
        });

        it('disconnects Tidal', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ status: 'ok', message: 'Tidal disconnected' }),
          });

          const result = await api.disconnectTidal();
          expect(result.status).toBe('ok');

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/tidal/disconnect');
          expect(options.method).toBe('POST');
        });

        it('fetches Tidal event settings', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ tidal_sync_enabled: true }),
          });

          const settings = await api.getTidalEventSettings(42);
          expect(settings.tidal_sync_enabled).toBe(true);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/tidal/events/42/settings');
        });

        it('updates Tidal event settings', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ tidal_sync_enabled: false }),
          });

          const settings = await api.updateTidalEventSettings(42, { tidal_sync_enabled: false });
          expect(settings.tidal_sync_enabled).toBe(false);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/tidal/events/42/settings');
          expect(options.method).toBe('PUT');
        });

        it('searches Tidal tracks', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => [{ title: 'Tidal Track', artist: 'Tidal Artist', tidal_id: '99' }],
          });

          const results = await api.searchTidal('tidal query', 5);
          expect(results).toHaveLength(1);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/tidal/search');
          expect(url).toContain('q=tidal%20query');
          expect(url).toContain('limit=5');
        });

        it('syncs request to Tidal', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ status: 'synced', tidal_track_id: '123' }),
          });

          const result = await api.syncRequestToTidal(7);
          expect(result.status).toBe('synced');

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/tidal/requests/7/sync');
          expect(options.method).toBe('POST');
        });

        it('links Tidal track to request', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ status: 'linked', tidal_track_id: '456' }),
          });

          const result = await api.linkTidalTrack(7, '456');
          expect(result.tidal_track_id).toBe('456');

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/tidal/requests/7/link');
          expect(options.method).toBe('POST');
          expect(JSON.parse(options.body)).toEqual({ tidal_track_id: '456' });
        });
      });
  describe('Recommendations API', () => {
        beforeEach(() => {
        });

        it('generates recommendations', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              suggestions: [{ title: 'Rec Song', artist: 'Rec Artist', score: 0.95 }],
              profile: { avg_bpm: 128 },
            }),
          });

          const result = await api.generateRecommendations('ABC123');
          expect(result.suggestions).toHaveLength(1);
          expect(result.suggestions[0].score).toBe(0.95);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/ABC123/recommendations');
          expect(options.method).toBe('POST');
        });

        it('fetches event playlists', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              playlists: [{ id: 'pl1', name: 'My Playlist', source: 'tidal', track_count: 20 }],
            }),
          });

          const result = await api.getEventPlaylists('ABC123');
          expect(result.playlists).toHaveLength(1);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/ABC123/playlists');
        });

        it('generates LLM recommendations', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              suggestions: [{ title: 'AI Pick', artist: 'AI Artist' }],
              query_info: { model: 'claude-haiku-4-5-20251001', prompt_tokens: 100 },
            }),
          });

          const result = await api.generateLLMRecommendations('ABC123', 'something upbeat');
          expect(result.suggestions).toHaveLength(1);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/ABC123/recommendations/llm');
          expect(options.method).toBe('POST');
          const body = JSON.parse(options.body);
          expect(body.prompt).toBe('something upbeat');
        });

        it('generates recommendations from template playlist', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              suggestions: [{ title: 'Template Pick', artist: 'Template Artist' }],
            }),
          });

          const result = await api.generateRecommendationsFromTemplate('ABC123', 'tidal', 'pl-123');
          expect(result.suggestions).toHaveLength(1);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/ABC123/recommendations/from-template');
          expect(options.method).toBe('POST');
          const body = JSON.parse(options.body);
          expect(body.source).toBe('tidal');
          expect(body.playlist_id).toBe('pl-123');
        });
      });
  describe('Banner API', () => {
        beforeEach(() => {
        });

        it('uploads event banner with FormData (no Content-Type header)', async () => {
          const mockResponse = {
            ok: true,
            json: async () => ({
              id: 1, code: 'ABC123', name: 'Test Event', created_at: '2026-01-01T00:00:00Z',
              expires_at: '2026-12-31T00:00:00Z', is_active: true, join_url: null,
              tidal_sync_enabled: false, tidal_playlist_id: null,
              beatport_sync_enabled: false, beatport_playlist_id: null,
              banner_url: '/uploads/banners/banner.webp', banner_kiosk_url: '/uploads/banners/banner_kiosk.webp',
              banner_colors: null, requests_open: true,
            }),
            status: 200,
          };
          mockFetch.mockResolvedValueOnce(mockResponse);

          const file = new File(['fake-image-data'], 'banner.png', { type: 'image/png' });
          const result = await api.uploadEventBanner('ABC123', file);
          expect(result.banner_url).toBe('/uploads/banners/banner.webp');

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/ABC123/banner');
          expect(options.method).toBe('POST');
          expect(options.body).toBeInstanceOf(FormData);
          // rawFetch does NOT set Content-Type — browser sets multipart boundary
          const headers = new Headers(options.headers);
          expect(headers.get('Content-Type')).toBeNull();
        });

        it('propagates error on upload failure', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: false,
            status: 413,
            json: async () => ({ detail: 'File too large' }),
          });

          await expect(api.uploadEventBanner('ABC123', new File(['x'], 'big.png'))).rejects.toThrow(
            'File too large'
          );
        });

        it('deletes event banner', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              id: 1, code: 'ABC123', name: 'Test Event', created_at: '2026-01-01T00:00:00Z',
              expires_at: '2026-12-31T00:00:00Z', is_active: true, join_url: null,
              tidal_sync_enabled: false, tidal_playlist_id: null,
              beatport_sync_enabled: false, beatport_playlist_id: null,
              banner_url: null, banner_kiosk_url: null,
              banner_colors: null, requests_open: true,
            }),
          });

          const result = await api.deleteEventBanner('ABC123');
          expect(result.banner_url).toBeNull();

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/ABC123/banner');
          expect(options.method).toBe('DELETE');
        });
      });
  describe('streamConnectorTest', () => {
        it('parses SSE data frames and invokes onChunk per frame', async () => {
          const sse =
            'data: {"text_delta":"Hi","done":false}\n\n' +
            'data: {"text_delta":" there","done":false}\n\n' +
            'data: {"text_delta":"","stop_reason":"end_turn","done":true}\n\n';
          const encoder = new TextEncoder();
          const stream = new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(encoder.encode(sse));
              controller.close();
            },
          });
          const fetchMock = vi.spyOn(global, 'fetch').mockResolvedValueOnce(
            new Response(stream, {
              status: 200,
              headers: { 'Content-Type': 'text/event-stream' },
            }),
          );

          const chunks: Array<{ text_delta?: string; done?: boolean }> = [];
          await api.streamConnectorTest(7, (c) => chunks.push(c));

          expect(chunks.map((c) => c.text_delta).join('')).toBe('Hi there');
          expect(chunks.at(-1)?.done).toBe(true);

          const init = fetchMock.mock.calls[0][1] as RequestInit;
          const headers = new Headers(init.headers);
          expect(headers.get('Authorization')).toBeNull();
          expect(init.credentials).toBe('include');
          expect(init.method).toBe('POST');
        });

        it('parses CRLF-delimited SSE frames, including event: error (#354)', async () => {
          // A spec-compliant server or proxy may frame SSE with CRLF (\r\n\r\n)
          // rather than LF. The parser must split frames and lines on either, or it
          // silently drops every frame — including the typed `event: error`.
          const sse =
            'data: {"text_delta":"Hi","done":false}\r\n\r\n' +
            'event: error\r\ndata: {"code":"ProviderUnavailable"}\r\n\r\n';
          const encoder = new TextEncoder();
          const stream = new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(encoder.encode(sse));
              controller.close();
            },
          });
          vi.spyOn(global, 'fetch').mockResolvedValueOnce(
            new Response(stream, {
              status: 200,
              headers: { 'Content-Type': 'text/event-stream' },
            }),
          );

          const chunks: Array<{ text_delta?: string }> = [];
          await expect(
            api.streamConnectorTest(7, (c) => chunks.push(c)),
          ).rejects.toThrowError(/ProviderUnavailable/);
          // The CRLF-framed data frame before the error was still parsed.
          expect(chunks.map((c) => c.text_delta).join('')).toBe('Hi');
        });

        // Regression for baseline 57cfcdc6867f: JSON parsing alone does not validate the stream contract.
        it('does not pass malformed or wrong-shaped SSE payloads to the consumer', async () => {
          const sse =
            'data: {not-json}\n\n' +
            'data: {"text_delta":42}\n\n' +
            'data: {"unexpected":true}\n\n' +
            'data: {"tool_call_deltas":[{"index":-1}]}\n\n' +
            'data: {"usage":{"prompt":"many","completion":1}}\n\n' +
            'data: {"text_delta":"valid","done":false}\n\n';
          const encoder = new TextEncoder();
          const stream = new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(encoder.encode(sse));
              controller.close();
            },
          });
          vi.spyOn(global, 'fetch').mockResolvedValueOnce(
            new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }),
          );
          const chunks: unknown[] = [];

          await api.streamConnectorTest(7, (chunk) => chunks.push(chunk));

          expect(chunks).toEqual([{ text_delta: 'valid', done: false }]);
        });

        it('throws ApiError on non-OK response', async () => {
          vi.spyOn(global, 'fetch').mockResolvedValueOnce(
            new Response('nope', { status: 500 }),
          );
          await expect(api.streamConnectorTest(7, () => {})).rejects.toBeInstanceOf(ApiError);
        });

        // Regression for baseline 57cfcdc6867f: consumer failures must not look like a clean stream.
        it('propagates errors thrown by the chunk consumer', async () => {
          const encoder = new TextEncoder();
          const stream = new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(encoder.encode('data: {"text_delta":"Hi"}\n\n'));
              controller.close();
            },
          });
          vi.spyOn(global, 'fetch').mockResolvedValueOnce(
            new Response(stream, {
              status: 200,
              headers: { 'Content-Type': 'text/event-stream' },
            }),
          );
          const consumerError = new Error('consumer failed');

          await expect(api.streamConnectorTest(7, () => { throw consumerError; }))
            .rejects.toBe(consumerError);
        });

        it('surfaces an SSE event: error frame as a thrown ApiError (#379)', async () => {
          // The backend emits `event: error` + a sanitised `{code}` data line for
          // typed gateway failures; the consumer must reject, not swallow it.
          const sse =
            'data: {"text_delta":"partial","done":false}\n\n' +
            'event: error\ndata: {"code":"ProviderUnavailable"}\n\n';
          const encoder = new TextEncoder();
          const stream = new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(encoder.encode(sse));
              controller.close();
            },
          });
          vi.spyOn(global, 'fetch').mockResolvedValueOnce(
            new Response(stream, {
              status: 200,
              headers: { 'Content-Type': 'text/event-stream' },
            }),
          );

          const chunks: Array<{ text_delta?: string }> = [];
          await expect(
            api.streamConnectorTest(7, (c) => chunks.push(c)),
          ).rejects.toThrowError(/ProviderUnavailable/);
          // The leading valid chunk was still delivered before the error surfaced.
          expect(chunks.map((c) => c.text_delta).join('')).toBe('partial');
        });
      });
});
