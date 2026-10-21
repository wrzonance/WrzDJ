import { describe, it, expect, vi } from 'vitest';
import { api, ApiError, withHumanRetry, HumanVerificationRequiredError, CSRF_HEADER_NAME, CSRF_HEADER_VALUE } from '..';
import { mockFetch, setupApiClient } from './api-test-setup';

describe('ApiClient auth', () => {
  setupApiClient();
  describe('login', () => {
        it('sends credentials as form data', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ access_token: 'test-token' }),
          });

          await expect(api.login('testuser', 'testpass')).resolves.toBeUndefined();

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
  describe('getMe', () => {
        it('returns user info including role', async () => {
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

        it('uses the cookie session without attaching a stale bearer token (#754)', async () => {
          // Regression pinned to baseline 57cfcdc6867f: dashboard cookie requests
          // must not revive a token-based auth path.
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ id: 1, username: 'testuser', role: 'admin' }),
          });

          await api.getMe();

          const [, options] = mockFetch.mock.calls[0];
          expect(new Headers(options.headers).get('Authorization')).toBeNull();
          expect(options.credentials).toBe('include');
        });
      });

  it('rejects an unexpected 204 from a JSON request instead of returning undefined as T', async () => {
    // Regression pinned to baseline 57cfcdc6867f: JSON-returning methods must
    // not silently receive an undefined value typed as their response model.
    mockFetch.mockResolvedValueOnce({ ok: true, status: 204 });

    await expect(api.getMe()).rejects.toMatchObject({ status: 204 });
  });
  describe('error handling', () => {
        it('throws with detail from error response', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: false,
            json: async () => ({ detail: 'Event not found' }),
          });

          await expect(api.getEvent('INVALID')).rejects.toThrow('Event not found');
        });

        it('throws generic message when no detail', async () => {
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

        it.each([
          [401, 'Invalid credentials'],
          [429, 'Too many attempts. Try again later.'],
          [500, 'Login failed. Please try again.'],
        ])('preserves status %i in ApiError without changing its safe message', async (status, message) => {
          mockFetch.mockResolvedValueOnce({ ok: false, status });

          await expect(api.login('user', 'pass')).rejects.toMatchObject({
            name: 'ApiError',
            status,
            message,
          });
        });
      });
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
          mockFetch.mockResolvedValueOnce({
            ok: true,
            status: 200,
            json: async () => ({ status: 'ok', message: 'OK' }),
          });

          await api.markHelpPageSeen('dashboard');

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/auth/help-seen');
          expect(options.method).toBe('POST');
          expect(JSON.parse(options.body)).toEqual({ page: 'dashboard' });
        });
      });
  describe('cascade: 401 on any authenticated method triggers handler', () => {
        it('triggers onUnauthorized for getRequests 401', async () => {
          const handler = vi.fn();
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

          await api.submitRequest({ eventCode: 'TEST01', artist: 'Artist', title: 'Title' });

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
  describe('frictionless join api', () => {
        it('getJoinConfig hits the public collect endpoint', async () => {
          mockFetch.mockResolvedValueOnce(
            new Response(JSON.stringify({ frictionless_join: true }), { status: 200 }),
          );
          const res = await api.getJoinConfig('CODE01');
          expect(res.frictionless_join).toBe(true);
          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/public/collect/CODE01/join-config');
        });

        it('ensureGuestName posts to the ensure-name endpoint', async () => {
          mockFetch.mockResolvedValueOnce(
            new Response(
              JSON.stringify({ nickname: 'DancingPanda', auto_generated: true }),
              { status: 200 },
            ),
          );
          const res = await api.ensureGuestName('CODE01');
          expect(res.nickname).toBe('DancingPanda');
          const [url, init] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/public/collect/CODE01/guest/ensure-name');
          expect(init.method).toBe('POST');
        });

        it('ensureGuestName sends the chosen nickname when renaming', async () => {
          mockFetch.mockResolvedValueOnce(
            new Response(
              JSON.stringify({ nickname: 'Alex', auto_generated: false }),
              { status: 200 },
            ),
          );
          const res = await api.ensureGuestName('CODE01', { nickname: 'Alex' });
          expect(res.nickname).toBe('Alex');
          const [, init] = mockFetch.mock.calls[0];
          expect(JSON.parse(init.body)).toEqual({ nickname: 'Alex' });
        });

        it('updateMyPreferences PATCHes the preferences endpoint', async () => {
          mockFetch.mockResolvedValueOnce(
            new Response(JSON.stringify({ frictionless_join_default: true }), { status: 200 }),
          );
          await api.updateMyPreferences({ frictionless_join_default: true });
          const [url, init] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/auth/me/preferences');
          expect(init.method).toBe('PATCH');
          expect(JSON.parse(init.body)).toEqual({ frictionless_join_default: true });
        });
      });
  describe('withHumanRetry', () => {
        const verificationRequired403 = () =>
          new Response(JSON.stringify({ detail: { code: 'human_verification_required' } }), {
            status: 403,
          });

        it('calls reverify and retries once on 403 human_verification_required', async () => {
          const responses = [
            verificationRequired403(),
            new Response(JSON.stringify({ ok: true }), { status: 200 }),
          ];
          const doFetch = vi.fn(async () => responses.shift()!);
          const reverify = vi.fn().mockResolvedValue(undefined);

          const result = await withHumanRetry<{ ok: boolean }>(doFetch, reverify);

          expect(reverify).toHaveBeenCalledTimes(1);
          expect(doFetch).toHaveBeenCalledTimes(2);
          expect(result).toEqual({ ok: true });
        });

        it('throws HumanVerificationRequiredError when still 403 after the retry', async () => {
          const doFetch = vi.fn(async () => verificationRequired403());
          const reverify = vi.fn().mockResolvedValue(undefined);

          await expect(withHumanRetry(doFetch, reverify)).rejects.toBeInstanceOf(
            HumanVerificationRequiredError,
          );
          expect(doFetch).toHaveBeenCalledTimes(2);
        });

        it('propagates a reverify rejection without retrying the fetch', async () => {
          const doFetch = vi.fn(async () => verificationRequired403());
          const reverify = vi.fn().mockRejectedValue(new Error('human_verification_failed'));

          await expect(withHumanRetry(doFetch, reverify)).rejects.toThrow('human_verification_failed');
          expect(doFetch).toHaveBeenCalledTimes(1);
        });

        it('preserves a structured provider error code and detail for recovery handling', async () => {
          const detail = {
            code: 'apple_music_write_uncertain',
            message: 'Do not retry; check your library.',
            playlist_id: 'p.playlist123',
          };
          const doFetch = vi.fn(async () => new Response(JSON.stringify({ detail }), { status: 502 }));

          const error = await withHumanRetry(doFetch, vi.fn()).catch((caught: unknown) => caught);

          expect(error).toBeInstanceOf(ApiError);
          expect(error).toMatchObject({
            message: detail.message,
            code: detail.code,
            detail,
          });
        });
      });
  describe('cookie session (#754)', () => {
        it('login sends credentials so the HttpOnly session cookie is stored', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            status: 200,
            json: async () => ({ access_token: 'ignored', token_type: 'bearer' }),
          });
          await api.login('dj', 'pw');
          const [, options] = mockFetch.mock.calls[0];
          expect(options.credentials).toBe('include');
          // Without this header the API returns the token but issues no cookie (login CSRF).
          expect(options.headers[CSRF_HEADER_NAME]).toBe(CSRF_HEADER_VALUE);
        });

        it('authenticated requests carry the CSRF header and credentials', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            status: 200,
            json: async () => ({ id: 1, username: 'dj', role: 'dj', help_pages_seen: [] }),
          });
          await api.getMe();
          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/auth/me');
          expect(options.credentials).toBe('include');
          expect(options.headers.get(CSRF_HEADER_NAME)).toBe(CSRF_HEADER_VALUE);
          expect(options.headers.get('Authorization')).toBeNull();
        });

        it('endSession DELETEs /api/auth/session with credentials', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            status: 200,
            json: async () => ({ status: 'ok', message: 'Session ended' }),
          });
          await api.endSession();
          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/auth/session');
          expect(options.method).toBe('DELETE');
          expect(options.credentials).toBe('include');
          expect(options.headers.get(CSRF_HEADER_NAME)).toBe(CSRF_HEADER_VALUE);
        });
      });
});
