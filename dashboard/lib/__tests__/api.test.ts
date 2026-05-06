import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { api, ApiError } from '../api';

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

describe('ApiClient', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    api.setToken(null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('login', () => {
    it('sends credentials as form data', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ access_token: 'test-token' }),
      });

      const result = await api.login('testuser', 'testpass');

      expect(result.access_token).toBe('test-token');
      expect(mockFetch).toHaveBeenCalledTimes(1);

      const [url, options] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/auth/login');
      expect(options.method).toBe('POST');
      expect(options.headers['Content-Type']).toBe('application/x-www-form-urlencoded');
    });

    it('throws on invalid credentials', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
      });

      await expect(api.login('bad', 'creds')).rejects.toThrow('Invalid credentials');
    });
  });

  describe('getEvents', () => {
    it('fetches events with auth header', async () => {
      api.setToken('test-token');
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => [{ id: 1, code: 'ABC123', name: 'Test Event' }],
      });

      const events = await api.getEvents();

      expect(events).toHaveLength(1);
      expect(events[0].code).toBe('ABC123');

      const [, options] = mockFetch.mock.calls[0];
      // Headers is a Headers object, use .get() to retrieve values
      expect(options.headers.get('Authorization')).toBe('Bearer test-token');
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

      const result = await api.submitRequest('ABC123', 'Artist', 'Title', 'Please play!');

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
      expect(url).toContain('/api/public/e/ABC123/history');
      expect(url).toContain('limit=10');
      expect(url).toContain('offset=0');
    });

    it('fetches play history with custom limit and offset', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ items: [], total: 0 }),
      });

      await api.getPlayHistory('ABC123', 5, 10);

      const [url] = mockFetch.mock.calls[0];
      expect(url).toContain('limit=5');
      expect(url).toContain('offset=10');
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
      api.setToken('test-token');

      const mockBlob = new Blob(['csv,content'], { type: 'text/csv' });
      mockFetch.mockResolvedValueOnce({
        ok: true,
        blob: async () => mockBlob,
        headers: new Headers({
          'Content-Disposition': 'attachment; filename="ABC123_play_history_20260205.csv"',
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

      await api.exportPlayHistoryCsv('ABC123');

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
      api.setToken('test-token');
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: 'Event not found' }),
      });

      await expect(api.exportPlayHistoryCsv('INVALID')).rejects.toThrow('Event not found');
    });

    it('includes auth token in request', async () => {
      api.setToken('my-auth-token');

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
      expect(options.headers.get('Authorization')).toBe('Bearer my-auth-token');
    });
  });

  describe('getMe', () => {
    it('returns user info including role', async () => {
      api.setToken('test-token');
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 1, username: 'testuser', role: 'admin' }),
      });

      const user = await api.getMe();

      expect(user.id).toBe(1);
      expect(user.username).toBe('testuser');
      expect(user.role).toBe('admin');

      const [url] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/auth/me');
    });
  });

  describe('admin API', () => {
    beforeEach(() => {
      api.setToken('admin-token');
    });

    it('fetches admin stats', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          total_users: 5,
          active_users: 4,
          pending_users: 1,
          total_events: 10,
          active_events: 3,
          total_requests: 50,
        }),
      });

      const stats = await api.getAdminStats();
      expect(stats.total_users).toBe(5);
      expect(stats.pending_users).toBe(1);

      const [url] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/admin/stats');
    });

    it('fetches admin users with role filter', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          items: [{ id: 1, username: 'dj1', role: 'dj' }],
          total: 1,
          page: 1,
          limit: 20,
        }),
      });

      const result = await api.getAdminUsers(1, 20, 'dj');
      expect(result.items).toHaveLength(1);

      const [url] = mockFetch.mock.calls[0];
      expect(url).toContain('role=dj');
    });

    it('creates admin user', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 2, username: 'newdj', role: 'dj' }),
      });

      const user = await api.createAdminUser({
        username: 'newdj',
        password: 'password123',
        role: 'dj',
      });
      expect(user.username).toBe('newdj');

      const [, options] = mockFetch.mock.calls[0];
      expect(options.method).toBe('POST');
    });

    it('updates admin settings', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          registration_enabled: false,
          search_rate_limit_per_minute: 50,
        }),
      });

      const settings = await api.updateAdminSettings({
        registration_enabled: false,
      });
      expect(settings.registration_enabled).toBe(false);
    });
  });

  describe('error handling', () => {
    it('throws with detail from error response', async () => {
      api.setToken('token');
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: 'Event not found' }),
      });

      await expect(api.getEvent('INVALID')).rejects.toThrow('Event not found');
    });

    it('throws generic message when no detail', async () => {
      api.setToken('token');
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({}),
      });

      await expect(api.getEvent('INVALID')).rejects.toThrow('Request failed');
    });
  });

  describe('401 unauthorized handler', () => {
    it('calls onUnauthorized when authenticated endpoint returns 401', async () => {
      const handler = vi.fn();
      api.setToken('expired-token');
      api.setUnauthorizedHandler(handler);

      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({ detail: 'Not authenticated' }),
      });

      await expect(api.getEvents()).rejects.toThrow('Not authenticated');
      expect(handler).toHaveBeenCalledOnce();

      api.setUnauthorizedHandler(null);
    });

    it('does not call onUnauthorized for login 401 (raw fetch)', async () => {
      const handler = vi.fn();
      api.setUnauthorizedHandler(handler);

      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
      });

      await expect(api.login('user', 'wrong')).rejects.toThrow('Invalid credentials');
      // login uses raw fetch, not this.fetch(), so handler should NOT fire
      expect(handler).not.toHaveBeenCalled();

      api.setUnauthorizedHandler(null);
    });
  });

  describe('login error differentiation', () => {
    it('returns "Invalid credentials" for 401', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 401 });
      await expect(api.login('user', 'wrong')).rejects.toThrow('Invalid credentials');
    });

    it('returns "Too many attempts" for 429', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 429 });
      await expect(api.login('user', 'pass')).rejects.toThrow('Too many attempts. Try again later.');
    });

    it('returns generic message for other errors', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });
      await expect(api.login('user', 'pass')).rejects.toThrow('Login failed. Please try again.');
    });
  });

  describe('AI Settings API', () => {
    beforeEach(() => {
      api.setToken('admin-token');
    });

    it('fetches AI models', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          models: [
            { id: 'claude-haiku-4-5-20251001', name: 'Claude Haiku 4.5' },
          ],
        }),
      });

      const result = await api.getAIModels();
      expect(result.models).toHaveLength(1);
      expect(result.models[0].id).toBe('claude-haiku-4-5-20251001');

      const [url] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/admin/ai/models');
    });

    it('fetches AI settings', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          llm_enabled: true,
          llm_model: 'claude-haiku-4-5-20251001',
          llm_rate_limit_per_minute: 3,
          api_key_configured: true,
          api_key_masked: '...test',
        }),
      });

      const result = await api.getAISettings();
      expect(result.llm_enabled).toBe(true);
      expect(result.api_key_configured).toBe(true);
    });

    it('updates AI settings', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          llm_enabled: false,
          llm_model: 'claude-sonnet-4-5-20250929',
          llm_rate_limit_per_minute: 5,
          api_key_configured: true,
          api_key_masked: '...test',
        }),
      });

      const result = await api.updateAISettings({
        llm_enabled: false,
        llm_model: 'claude-sonnet-4-5-20250929',
      });
      expect(result.llm_enabled).toBe(false);

      const [, options] = mockFetch.mock.calls[0];
      expect(options.method).toBe('PUT');
    });
  });

  describe('Activity Log API', () => {
    beforeEach(() => {
      api.setToken('test-token');
    });

    it('fetches activity log', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => [
          {
            id: 1,
            created_at: '2026-01-01T00:00:00Z',
            level: 'info',
            source: 'bridge',
            message: 'Bridge connected',
            event_code: 'ABC123',
          },
        ],
      });

      const result = await api.getActivityLog();
      expect(result).toHaveLength(1);
      expect(result[0].source).toBe('bridge');

      const [url] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/events/activity');
    });

    it('passes event_code filter', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => [],
      });

      await api.getActivityLog('ABC123');

      const [url] = mockFetch.mock.calls[0];
      expect(url).toContain('event_code=ABC123');
    });
  });

  describe('Beatport API', () => {
    beforeEach(() => {
      api.setToken('test-token');
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

  describe('deleteEvent', () => {
    it('sends DELETE request with auth header', async () => {
      api.setToken('test-token');
      mockFetch.mockResolvedValueOnce({ ok: true });

      await api.deleteEvent('ABC123');

      const [url, options] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/events/ABC123');
      expect(options.method).toBe('DELETE');
      expect(options.headers.get('Authorization')).toBe('Bearer test-token');
    });

    it('throws on failure with detail message', async () => {
      api.setToken('test-token');
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: 'Event not found' }),
      });

      await expect(api.deleteEvent('INVALID')).rejects.toThrow('Event not found');
    });

    it('throws generic message when json parsing fails', async () => {
      api.setToken('test-token');
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

    it('returns null for other errors', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });

      const result = await api.getNowPlaying('ABC123');
      expect(result).toBeNull();
    });
  });

  describe('exportEventCsv', () => {
    it('downloads event CSV with correct URL', async () => {
      api.setToken('test-token');

      const mockBlob = new Blob(['csv,content'], { type: 'text/csv' });
      mockFetch.mockResolvedValueOnce({
        ok: true,
        blob: async () => mockBlob,
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

      await api.exportEventCsv('ABC123');

      const [url] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/events/ABC123/export/csv');
    });

    it('throws ApiError on failure', async () => {
      api.setToken('test-token');
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 403,
        json: async () => ({ detail: 'Forbidden' }),
      });

      await expect(api.exportEventCsv('ABC123')).rejects.toThrow('Forbidden');
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
      api.setToken('dj-token');
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
      api.setToken('dj-token');
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
      api.setToken('dj-token');
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
      api.setToken('dj-token');
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
      api.setToken('dj-token');
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

  // ========== Phase 1: Auth & User endpoints ==========

  describe('getPublicSettings', () => {
    it('fetches registration settings without auth', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ registration_enabled: true, turnstile_site_key: 'key123' }),
      });

      const settings = await api.getPublicSettings();
      expect(settings.registration_enabled).toBe(true);
      expect(settings.turnstile_site_key).toBe('key123');

      const [url] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/auth/settings');
    });
  });

  describe('register', () => {
    it('sends registration data', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ status: 'ok', message: 'Registration successful' }),
      });

      const result = await api.register({
        username: 'newuser',
        email: 'new@test.com',
        password: 'pass123',
        confirm_password: 'pass123',
        turnstile_token: 'token-abc',
      });
      expect(result.status).toBe('ok');

      const [url, options] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/auth/register');
      expect(options.method).toBe('POST');
      const body = JSON.parse(options.body);
      expect(body.username).toBe('newuser');
      expect(body.turnstile_token).toBe('token-abc');
    });

    it('throws ApiError on 409 conflict', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({ detail: 'Username already taken' }),
      });

      try {
        await api.register({
          username: 'existing',
          email: 'e@test.com',
          password: 'pass',
          confirm_password: 'pass',
          turnstile_token: 'tok',
        });
        expect.fail('should have thrown');
      } catch (e) {
        expect(e).toBeInstanceOf(ApiError);
        expect((e as ApiError).message).toBe('Username already taken');
        expect((e as ApiError).status).toBe(409);
      }
    });

    it('throws generic error when json parsing fails', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => { throw new Error('not json'); },
      });

      await expect(api.register({
        username: 'x',
        email: 'x@test.com',
        password: 'p',
        confirm_password: 'p',
        turnstile_token: 't',
      })).rejects.toThrow('Registration failed');
    });
  });

  describe('markHelpPageSeen', () => {
    it('sends help page POST request', async () => {
      api.setToken('test-token');
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 204,
        json: async () => undefined,
      });

      await api.markHelpPageSeen('dashboard');

      const [url, options] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/auth/help-seen');
      expect(options.method).toBe('POST');
      expect(JSON.parse(options.body)).toEqual({ page: 'dashboard' });
    });
  });

  // ========== Events CRUD ==========

  describe('createEvent', () => {
    it('creates event with name and default expiry', async () => {
      api.setToken('test-token');
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
      api.setToken('test-token');
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
      api.setToken('test-token');
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
      api.setToken('test-token');
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
      api.setToken('test-token');
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

  // ========== Request Management ==========

  describe('getRequests', () => {
    it('fetches all requests for an event', async () => {
      api.setToken('test-token');
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => [
          { id: 1, artist: 'A', song_title: 'S', status: 'new' },
          { id: 2, artist: 'B', song_title: 'T', status: 'accepted' },
        ],
      });

      const requests = await api.getRequests('ABC123');
      expect(requests).toHaveLength(2);

      const [url] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/events/ABC123/requests');
      expect(url).not.toContain('status=');
    });

    it('filters requests by status', async () => {
      api.setToken('test-token');
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => [{ id: 1, status: 'new' }],
      });

      await api.getRequests('ABC123', { status: 'new' });

      const [url] = mockFetch.mock.calls[0];
      expect(url).toContain('status=new');
    });

    it('appends sort parameter when specified', async () => {
      api.setToken('test-token');
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => [{ id: 1, status: 'new', priority_score: 0.85 }],
      });

      await api.getRequests('ABC123', { sort: 'priority' });

      const [url] = mockFetch.mock.calls[0];
      expect(url).toContain('sort=priority');
    });

    it('omits sort parameter by default', async () => {
      api.setToken('test-token');
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => [],
      });

      await api.getRequests('ABC123');

      const [url] = mockFetch.mock.calls[0];
      expect(url).not.toContain('sort=');
    });
  });

  describe('acceptAllRequests', () => {
    it('accepts all pending requests', async () => {
      api.setToken('test-token');
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

  describe('updateRequestStatus', () => {
    it('updates request status', async () => {
      api.setToken('test-token');
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
      api.setToken('test-token');
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

  // ========== Public endpoints ==========

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
  });

  describe('getKioskDisplay', () => {
    it('fetches kiosk display data', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          event: { code: 'FRI001', name: 'Friday Night' },
          qr_join_url: 'https://example.com/join/FRI001',
          accepted_queue: [],
          now_playing: null,
          now_playing_hidden: false,
          requests_open: true,
          kiosk_display_only: false,
          updated_at: '2026-01-01T00:00:00Z',
          banner_url: null,
          banner_kiosk_url: null,
          banner_colors: null,
        }),
      });

      const result = await api.getKioskDisplay('FRI001');
      expect(result.event.name).toBe('Friday Night');

      const [url] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/public/events/FRI001/display');
    });
  });

  // ========== Voting ==========

  describe('voteRequest', () => {
    it('sends authenticated vote', async () => {
      api.setToken('test-token');
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
      api.setToken('test-token');
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

  // ========== Display Settings ==========

  describe('setNowPlayingVisibility', () => {
    it('sets now playing hidden', async () => {
      api.setToken('test-token');
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
      api.setToken('test-token');
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
      api.setToken('test-token');
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
      api.setToken('test-token');
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
      api.setToken('test-token');
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
      api.setToken('test-token');
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

  // ========== Tidal Integration ==========

  describe('Tidal API', () => {
    beforeEach(() => {
      api.setToken('test-token');
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

  // ========== Recommendations ==========

  describe('Recommendations API', () => {
    beforeEach(() => {
      api.setToken('test-token');
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

  // ========== Banner ==========

  describe('Banner API', () => {
    beforeEach(() => {
      api.setToken('test-token');
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

  // ========== Admin extended ==========

  describe('admin users extended', () => {
    beforeEach(() => {
      api.setToken('admin-token');
    });

    it('updates admin user role', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 5, username: 'user5', role: 'admin' }),
      });

      const result = await api.updateAdminUser(5, { role: 'admin' });
      expect(result.role).toBe('admin');

      const [url, options] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/admin/users/5');
      expect(options.method).toBe('PATCH');
    });

    it('deletes admin user', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 204,
        json: async () => undefined,
      });

      await api.deleteAdminUser(5);

      const [url, options] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/admin/users/5');
      expect(options.method).toBe('DELETE');
    });
  });

  describe('admin events', () => {
    beforeEach(() => {
      api.setToken('admin-token');
    });

    it('fetches admin events with pagination', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          items: [{ code: 'E1', name: 'Event 1', owner_username: 'dj1' }],
          total: 1,
          page: 2,
          limit: 10,
        }),
      });

      const result = await api.getAdminEvents(2, 10);
      expect(result.items).toHaveLength(1);
      expect(result.page).toBe(2);

      const [url] = mockFetch.mock.calls[0];
      expect(url).toContain('page=2');
      expect(url).toContain('limit=10');
    });

    it('updates admin event', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ code: 'E1', name: 'Updated Name' }),
      });

      const result = await api.updateAdminEvent('E1', { name: 'Updated Name' });
      expect(result.name).toBe('Updated Name');

      const [url, options] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/admin/events/E1');
      expect(options.method).toBe('PATCH');
    });

    it('deletes admin event', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 204,
        json: async () => undefined,
      });

      await api.deleteAdminEvent('E1');

      const [url, options] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/admin/events/E1');
      expect(options.method).toBe('DELETE');
    });
  });

  describe('admin settings (GET)', () => {
    it('fetches admin settings', async () => {
      api.setToken('admin-token');
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          registration_enabled: true,
          search_rate_limit_per_minute: 30,
          spotify_enabled: true,
          tidal_enabled: false,
        }),
      });

      const result = await api.getAdminSettings();
      expect(result.registration_enabled).toBe(true);
      expect(result.search_rate_limit_per_minute).toBe(30);

      const [url] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/admin/settings');
    });
  });

  // ========== Admin Integrations ==========

  describe('admin integrations', () => {
    beforeEach(() => {
      api.setToken('admin-token');
    });

    it('fetches all integration statuses', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          services: [
            { service: 'spotify', enabled: true, healthy: true },
            { service: 'tidal', enabled: false, healthy: false },
          ],
        }),
      });

      const result = await api.getIntegrations();
      expect(result.services).toHaveLength(2);

      const [url] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/admin/integrations');
    });

    it('toggles integration on/off', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ service: 'spotify', enabled: false }),
      });

      const result = await api.toggleIntegration('spotify', false);
      expect(result.enabled).toBe(false);

      const [url, options] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/admin/integrations/spotify');
      expect(options.method).toBe('PATCH');
      expect(JSON.parse(options.body)).toEqual({ enabled: false });
    });

    it('checks integration health', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          service: 'spotify',
          healthy: true,
          message: 'All checks passed',
        }),
      });

      const result = await api.checkIntegrationHealth('spotify');
      expect(result.healthy).toBe(true);

      const [url, options] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/admin/integrations/spotify/check');
      expect(options.method).toBe('POST');
    });
  });

  // ========== Cascade / boundary tests ==========

  describe('cascade: 401 on any authenticated method triggers handler', () => {
    it('triggers onUnauthorized for getRequests 401', async () => {
      const handler = vi.fn();
      api.setToken('expired-token');
      api.setUnauthorizedHandler(handler);

      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({ detail: 'Token expired' }),
      });

      await expect(api.getRequests('ABC123')).rejects.toThrow('Token expired');
      expect(handler).toHaveBeenCalledOnce();

      api.setUnauthorizedHandler(null);
    });

    it('triggers onUnauthorized for generateRecommendations 401', async () => {
      const handler = vi.fn();
      api.setToken('expired-token');
      api.setUnauthorizedHandler(handler);

      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({ detail: 'Not authenticated' }),
      });

      await expect(api.generateRecommendations('ABC123')).rejects.toThrow();
      expect(handler).toHaveBeenCalledOnce();

      api.setUnauthorizedHandler(null);
    });

    it('triggers onUnauthorized for uploadEventBanner 401 (rawFetch)', async () => {
      const handler = vi.fn();
      api.setToken('expired-token');
      api.setUnauthorizedHandler(handler);

      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({ detail: 'Not authenticated' }),
      });

      await expect(
        api.uploadEventBanner('ABC123', new File(['x'], 'test.png'))
      ).rejects.toThrow('Not authenticated');
      expect(handler).toHaveBeenCalledOnce();

      api.setUnauthorizedHandler(null);
    });
  });

  describe('cascade: register error differentiation', () => {
    it('409 error has different message than 500 error', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({ detail: 'Username already taken' }),
      });

      const err409 = await api.register({
        username: 'dup', email: 'd@t.com', password: 'p', confirm_password: 'p', turnstile_token: 't',
      }).catch((e: ApiError) => e);

      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => ({ detail: 'Internal server error' }),
      });

      const err500 = await api.register({
        username: 'x', email: 'x@t.com', password: 'p', confirm_password: 'p', turnstile_token: 't',
      }).catch((e: ApiError) => e);

      expect(err409.message).toBe('Username already taken');
      expect(err500.message).toBe('Internal server error');
      expect(err409.message).not.toBe(err500.message);
    });
  });

  describe('cascade: publicFetch error path', () => {
    it('throws ApiError with detail from public endpoint', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: async () => ({ detail: 'Event not found' }),
      });

      await expect(api.getPublicRequests('INVALID')).rejects.toThrow('Event not found');
    });

    it('throws generic error when json fails on public endpoint', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => { throw new Error('not json'); },
      });

      await expect(api.getKioskDisplay('BAD')).rejects.toThrow('Request failed');
    });
  });

  describe('credentials propagation (F2)', () => {
    it('submitRequest sends credentials: include', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 1, vote_count: 0 }),
      });

      await api.submitRequest('TEST01', 'Artist', 'Title');

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const [, options] = mockFetch.mock.calls[0];
      expect(options.credentials).toBe('include');
    });

    it('publicVoteRequest sends credentials: include', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ status: 'voted', vote_count: 1, has_voted: true }),
      });

      await api.publicVoteRequest(42);

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const [, options] = mockFetch.mock.calls[0];
      expect(options.credentials).toBe('include');
    });

    it('eventSearch sends credentials: include', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => [],
      });

      await api.eventSearch('TEST01', 'foo');

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const [, options] = mockFetch.mock.calls[0];
      expect(options.credentials).toBe('include');
    });
  });

  describe('email verification', () => {
    it('requestVerificationCode sends email and turnstile token and returns sent', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ sent: true }),
      });

      const result = await api.requestVerificationCode('fan@test.com', 'test-token');
      expect(result.sent).toBe(true);

      const [url, options] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/public/guest/verify/request');
      expect(options.credentials).toBe('include');
      expect(JSON.parse(options.body)).toEqual({ email: 'fan@test.com', turnstile_token: 'test-token' });
    });

    it('requestVerificationCode throws on error', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 429,
        json: async () => ({ detail: 'Too many codes requested' }),
      });

      await expect(api.requestVerificationCode('fan@test.com', 'test-token')).rejects.toThrow(
        'Too many codes requested'
      );
    });

    it('requestVerificationCode throws generic on json failure', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => { throw new Error('not json'); },
      });

      await expect(api.requestVerificationCode('fan@test.com', 'test-token')).rejects.toThrow(
        'Failed to send code'
      );
    });

    it('confirmVerificationCode sends code and returns result', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ verified: true, guest_id: 42, merged: false }),
      });

      const result = await api.confirmVerificationCode('fan@test.com', '847293');
      expect(result.verified).toBe(true);
      expect(result.guest_id).toBe(42);
      expect(result.merged).toBe(false);

      const [url, options] = mockFetch.mock.calls[0];
      expect(url).toContain('/api/public/guest/verify/confirm');
      expect(options.credentials).toBe('include');
      expect(JSON.parse(options.body)).toEqual({ email: 'fan@test.com', code: '847293' });
    });

    it('confirmVerificationCode throws on wrong code', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: async () => ({ detail: 'Incorrect verification code' }),
      });

      await expect(api.confirmVerificationCode('fan@test.com', '000000')).rejects.toThrow(
        'Incorrect verification code'
      );
    });

    it('confirmVerificationCode throws generic on json failure', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => { throw new Error('not json'); },
      });

      await expect(api.confirmVerificationCode('fan@test.com', '123456')).rejects.toThrow(
        'Verification failed'
      );
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
  });
});
