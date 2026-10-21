import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '..';

const fetchMock = vi.fn<typeof fetch>();

function response(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function lastRequest() {
  const [url, init] = fetchMock.mock.calls.at(-1) ?? [];
  if (!url) throw new Error('Expected one fetch request');
  return { url: new URL(String(url), 'http://localhost'), init: init ?? {} };
}

describe('API domain wire contracts through ApiClient transport', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
    api.setKioskSession(null);
    api.setUnauthorizedHandler(null);
  });

  afterEach(() => {
    api.setKioskSession(null);
    api.setUnauthorizedHandler(null);
    vi.unstubAllGlobals();
  });

  it('serializes password and email-change requests and encodes public confirmation tokens', async () => {
    fetchMock
      .mockResolvedValueOnce(response({ status: 'ok', message: 'Password updated' }))
      .mockResolvedValueOnce(response({ status: 'ok', message: 'Email sent' }))
      .mockResolvedValueOnce(response({ status: 'ok', message: 'Email confirmed' }));

    await api.changePassword({ current_password: 'old-secret', new_password: 'new-secret', confirm_new_password: 'new-secret' });
    let request = lastRequest();
    expect(request.url.pathname).toBe('/api/auth/me/password');
    expect(request.init.method).toBe('PATCH');
    expect(JSON.parse(String(request.init.body))).toEqual({
      current_password: 'old-secret', new_password: 'new-secret', confirm_new_password: 'new-secret',
    });
    expect(new Headers(request.init.headers).has('Authorization')).toBe(false);
    expect(request.init.credentials).toBe('include');
    expect(new Headers(request.init.headers).get('X-Requested-With')).toBe('WrzDJ');

    await api.requestEmailChange({ current_password: 'old-secret', new_email: 'new@example.com' });
    request = lastRequest();
    expect(request.url.pathname).toBe('/api/auth/me/email/request');
    expect(request.init.method).toBe('POST');
    expect(JSON.parse(String(request.init.body))).toEqual({ current_password: 'old-secret', new_email: 'new@example.com' });

    await api.confirmEmailChange('one/two + three');
    request = lastRequest();
    expect(request.url.pathname).toBe('/api/auth/email/confirm');
    expect(request.url.searchParams.get('token')).toBe('one/two + three');
    expect(request.init.method).toBeUndefined();
    expect(request.init.headers).toBeUndefined();
    expect(request.init.credentials).toBeUndefined();
  });

  it('preserves the password-change API error status and message', async () => {
    fetchMock.mockResolvedValueOnce(response({ detail: 'Current password is incorrect' }, 400));

    await expect(api.changePassword({
      current_password: 'wrong', new_password: 'new-secret', confirm_new_password: 'new-secret',
    })).rejects.toMatchObject({ name: 'ApiError', status: 400, message: 'Current password is incorrect' });
  });

  it('uses the Apple Music account lifecycle endpoints and reports link conflicts', async () => {
    fetchMock
      .mockResolvedValueOnce(response({ configured: true, linked: false, requires_reauthorization: false, storefront: null }))
      .mockResolvedValueOnce(response({ developer_token: 'signed-token', expires_at: 1_900_000_000 }))
      .mockResolvedValueOnce(response({ detail: 'Apple Music connect was canceled. Try connecting again.' }, 409))
      .mockResolvedValueOnce(response({ status: 'ok' }));

    await api.getAppleMusicStatus();
    let request = lastRequest();
    expect(request.url.pathname).toBe('/api/apple-music/status');
    expect(request.init.method).toBeUndefined();

    const developerToken = await api.getAppleMusicDeveloperToken();
    expect(developerToken.developer_token).toBe('signed-token');
    request = lastRequest();
    expect(request.url.pathname).toBe('/api/apple-music/developer-token');

    await expect(api.linkAppleMusicAccount('music-user-token'))
      .rejects.toMatchObject({ name: 'ApiError', status: 409 });
    request = lastRequest();
    expect(request.url.pathname).toBe('/api/apple-music/link');
    expect(request.init.method).toBe('POST');
    expect(JSON.parse(String(request.init.body))).toEqual({ music_user_token: 'music-user-token' });

    await api.disconnectAppleMusicAccount();
    request = lastRequest();
    expect(request.url.pathname).toBe('/api/apple-music/disconnect');
    expect(request.init.method).toBe('POST');
    for (const [, init] of fetchMock.mock.calls) {
      const headers = new Headers(init?.headers);
      expect(headers.has('Authorization')).toBe(false);
      expect(headers.get('X-Requested-With')).toBe('WrzDJ');
      expect(init?.credentials).toBe('include');
    }
  });

  it('rotates and revokes admin LLM credentials and downloads filtered audit CSV', async () => {
    fetchMock
      .mockResolvedValueOnce(response({ id: 4, name: 'Gateway', type: 'openai', is_active: true }))
      .mockResolvedValueOnce(response({ id: 4, name: 'Gateway', type: 'openai', is_active: false }))
      .mockResolvedValueOnce(new Response('event_type,actor_user_id\ncredential_rotated,2\n', {
        status: 200,
        headers: { 'Content-Type': 'text/csv', 'Content-Disposition': 'attachment; filename="audit.csv"' },
      }));

    await api.rotateLlmConnectorCredentials(4, { api_key: 'replacement-secret' });
    let request = lastRequest();
    expect(request.url.pathname).toBe('/api/llm/connectors/4/credentials');
    expect(request.init.method).toBe('PUT');
    expect(JSON.parse(String(request.init.body))).toEqual({ api_key: 'replacement-secret' });

    await api.revokeAdminLlmConnector(4);
    request = lastRequest();
    expect(request.url.pathname).toBe('/api/admin/llm/connectors/4/revoke');
    expect(request.init.method).toBe('POST');

    const csv = await api.downloadAdminLlmAuditCsv({
      event_type: 'credential_rotated', actor_user_id: 2, target_connector_id: 4, days: 7, limit: 20, offset: 40,
    });
    request = lastRequest();
    expect(request.url.pathname).toBe('/api/admin/llm/audit.csv');
    expect(request.url.searchParams.get('event_type')).toBe('credential_rotated');
    expect(request.url.searchParams.get('actor_user_id')).toBe('2');
    expect(request.url.searchParams.get('target_connector_id')).toBe('4');
    expect(request.url.searchParams.get('days')).toBe('7');
    expect(request.url.searchParams.has('limit')).toBe(false);
    expect(request.url.searchParams.has('offset')).toBe(false);
    expect(new Headers(fetchMock.mock.calls.at(-1)?.[1]?.headers).has('Authorization')).toBe(false);
    expect(await csv.text()).toContain('credential_rotated,2');
    for (const [, init] of fetchMock.mock.calls) {
      const headers = new Headers(init?.headers);
      expect(headers.has('Authorization')).toBe(false);
      expect(headers.get('X-Requested-With')).toBe('WrzDJ');
      expect(init?.credentials).toBe('include');
    }
  });

  it('reads and replaces a set document, then imports a pool URL with the server wire shape', async () => {
    const documentSnapshot = {
      settings: { vibe_theme: null, target_duration_sec: 3600, bpm_floor: null, bpm_ceiling: null, key_strictness: 0.2 },
      slots: [], curve_points: [], pool: { sources: [], tracks: [] },
    };
    fetchMock
      .mockResolvedValueOnce(response(documentSnapshot))
      .mockResolvedValueOnce(response(documentSnapshot))
      .mockResolvedValueOnce(response({ imported_count: 2, skipped_count: 0 }));

    await api.getSetDocument(42);
    let request = lastRequest();
    expect(request.url.pathname).toBe('/api/setbuilder/sets/42/document');
    expect(request.init.method).toBeUndefined();

    await api.putSetDocument(42, documentSnapshot);
    request = lastRequest();
    expect(request.url.pathname).toBe('/api/setbuilder/sets/42/document');
    expect(request.init.method).toBe('PUT');
    expect(JSON.parse(String(request.init.body))).toEqual(documentSnapshot);

    await api.importPoolUrl(42, 'https://open.spotify.com/playlist/abc');
    request = lastRequest();
    expect(request.url.pathname).toBe('/api/setbuilder/sets/42/pool/import/url');
    expect(request.init.method).toBe('POST');
    expect(JSON.parse(String(request.init.body))).toEqual({ url: 'https://open.spotify.com/playlist/abc' });
  });

  it('creates and accepts collaborator invites with encoded invitation tokens', async () => {
    fetchMock
      .mockResolvedValueOnce(response({ token: 'invite-secret', role: 'viewer', expires_at: '2026-11-01T00:00:00Z' }))
      .mockResolvedValueOnce(response({ set_id: 42, role: 'viewer' }));

    await api.createCollaboratorInvite(42, 'viewer');
    let request = lastRequest();
    expect(request.url.pathname).toBe('/api/setbuilder/sets/42/collaborator-invites');
    expect(request.init.method).toBe('POST');
    expect(JSON.parse(String(request.init.body))).toEqual({ role: 'viewer' });

    await api.acceptCollaboratorInvite('invite/token + secret');
    request = lastRequest();
    expect(request.url.pathname).toBe('/api/setbuilder/collaborator-invites/invite%2Ftoken%20%2B%20secret/accept');
    expect(request.init.method).toBe('POST');
    expect(request.init.body).toBeUndefined();
  });

  it('sends export preflight and file requests and reads the server filename', async () => {
    fetchMock
      .mockResolvedValueOnce(response({ target: 'rekordbox', total: 1, resolved_count: 1, unresolved: [] }))
      .mockResolvedValueOnce(new Response('<djplaylists/>', {
        status: 200,
        headers: { 'Content-Disposition': 'attachment; filename="Friday.xml"', 'Content-Type': 'application/xml' },
      }));

    await api.exportPreflight(42, 'rekordbox');
    let request = lastRequest();
    expect(request.url.pathname).toBe('/api/setbuilder/sets/42/export/preflight');
    expect(request.init.method).toBe('POST');
    expect(JSON.parse(String(request.init.body))).toEqual({ target: 'rekordbox' });

    const file = await api.exportSetFile(42, 'rekordbox', true, 'fallback.xml');
    request = lastRequest();
    expect(request.url.pathname).toBe('/api/setbuilder/sets/42/export/file');
    expect(request.init.method).toBe('POST');
    expect(JSON.parse(String(request.init.body))).toEqual({ format: 'rekordbox', skip_unresolved: true });
    expect(file.filename).toBe('Friday.xml');
    expect(await file.blob.text()).toBe('<djplaylists/>');
  });

  it('retries verified collection submission once and keeps vote requests credentialed', async () => {
    const song = { song_title: 'Night Drive', artist: 'DJ Example', source: 'manual' as const, isrc: 'USABC123' };
    const reverify = vi.fn().mockResolvedValue(undefined);
    fetchMock
      .mockResolvedValueOnce(response({ detail: { code: 'human_verification_required' } }, 403))
      .mockResolvedValueOnce(response({ id: 91, is_duplicate: false }, 201))
      .mockResolvedValueOnce(response({ detail: { code: 'human_verification_required' } }, 403))
      .mockResolvedValueOnce(response({ vote_count: 1, has_voted: true }));

    const submitted = await api.submitCollectRequest('COLLECT1', song, reverify);
    expect(submitted).toEqual({ id: 91, is_duplicate: false });
    expect(reverify).toHaveBeenCalledTimes(1);
    const submitRequests = fetchMock.mock.calls.slice(0, 2);
    expect(submitRequests.map(([url]) => new URL(String(url)).pathname)).toEqual([
      '/api/public/collect/COLLECT1/requests', '/api/public/collect/COLLECT1/requests',
    ]);
    for (const [, maybeInit] of submitRequests) {
      const init = maybeInit ?? {};
      expect(init.method).toBe('POST');
      expect(init.credentials).toBe('include');
      expect(JSON.parse(String(init.body))).toEqual(song);
      expect(new Headers(init.headers).has('Authorization')).toBe(false);
    }

    const voteReverify = vi.fn().mockResolvedValue(undefined);
    await api.voteCollectRequest('COLLECT1', 91, voteReverify);
    expect(voteReverify).toHaveBeenCalledTimes(1);
    const voteRequests = fetchMock.mock.calls.slice(2);
    expect(voteRequests.map(([url]) => new URL(String(url)).pathname)).toEqual([
      '/api/public/collect/COLLECT1/vote', '/api/public/collect/COLLECT1/vote',
    ]);
    expect(JSON.parse(String(voteRequests[0][1]?.body))).toEqual({ request_id: 91 });
    expect(voteRequests[0][1]?.credentials).toBe('include');
  });

  it('patches collection settings and invokes the Tidal sync route', async () => {
    fetchMock
      .mockResolvedValueOnce(response({ collection_opens_at: null, phase: 'collection', submission_cap_per_guest: 12 }))
      .mockResolvedValueOnce(response({ queued: 3 }));

    await api.patchCollectionSettings('EVENT1', { submission_cap_per_guest: 12, tidal_sync_enabled: true });
    let request = lastRequest();
    expect(request.url.pathname).toBe('/api/events/EVENT1/collection');
    expect(request.init.method).toBe('PATCH');
    expect(JSON.parse(String(request.init.body))).toEqual({ submission_cap_per_guest: 12, tidal_sync_enabled: true });

    const result = await api.syncCollectionToTidal('EVENT1');
    request = lastRequest();
    expect(result.queued).toBe(3);
    expect(request.url.pathname).toBe('/api/events/EVENT1/collection/sync-tidal');
    expect(request.init.method).toBe('POST');
    expect(request.init.body).toBeUndefined();
  });

  it('bulk-deletes events with the selected codes and reads public bridge status without auth', async () => {
    fetchMock
      .mockResolvedValueOnce(response({ status: 'ok', count: 2 }))
      .mockResolvedValueOnce(response({ connected: true, player_name: 'Deck A' }));

    const deletion = await api.bulkDeleteEvents(['EVT01', 'EVT02']);
    expect(deletion).toEqual({ status: 'ok', count: 2 });
    let request = lastRequest();
    expect(request.url.pathname).toBe('/api/events/bulk-delete');
    expect(request.init.method).toBe('POST');
    expect(JSON.parse(String(request.init.body))).toEqual({ codes: ['EVT01', 'EVT02'] });

    await api.getBridgeStatus('JOIN01');
    request = lastRequest();
    expect(request.url.pathname).toBe('/api/public/e/JOIN01/bridge-status');
    expect(request.init.method).toBeUndefined();
    expect(request.init.headers).toBeUndefined();
    expect(request.init.credentials).toBeUndefined();
  });

  // Regression for baseline 57cfcdc6867f: nickname and reverify options must not be ambiguous positional arguments.
  it('sends ensureGuestName nickname while keeping the verifier callback out of the body', async () => {
    const reverify = vi.fn().mockResolvedValue(undefined);
    fetchMock.mockResolvedValueOnce(response({ nickname: 'Alex', auto_generated: false }));

    const result = await api.ensureGuestName('CODE01', { nickname: 'Alex', reverify });

    expect(result.nickname).toBe('Alex');
    const { url, init } = lastRequest();
    expect(url.pathname).toBe('/api/public/collect/CODE01/guest/ensure-name');
    expect(init.method).toBe('POST');
    expect(init.credentials).toBe('include');
    expect(new Headers(init.headers).has('Authorization')).toBe(false);
    expect(JSON.parse(String(init.body))).toEqual({ nickname: 'Alex' });
    expect(reverify).not.toHaveBeenCalled();
  });

  // Regression for baseline 57cfcdc6867f: collection GETs discarded backend error details.
  it('preserves collection request credentials and exposes backend errors for simple reads', async () => {
    fetchMock
      .mockResolvedValueOnce(response({ code: 'COLLECT1', phase: 'collection' }))
      .mockResolvedValueOnce(response({ requests: [], total: 0, limit: 25, offset: 0 }))
      .mockResolvedValueOnce(response({ detail: 'Collection is closed' }, 403))
      .mockResolvedValueOnce(response({ detail: { code: 'email_verification_required', message: 'Verify your email' } }, 403))
      .mockResolvedValueOnce(response({ detail: 'Request not found' }, 404));

    await api.getCollectEvent('COLLECT1');
    let request = lastRequest();
    expect(request.url.pathname).toBe('/api/public/collect/COLLECT1');
    expect(request.init.method).toBe('GET');
    expect(request.init.credentials).toBeUndefined();

    await api.getCollectLeaderboard('COLLECT1', 'all', { limit: 10, offset: 20 });
    request = lastRequest();
    expect(request.url.pathname).toBe('/api/public/collect/COLLECT1/leaderboard');
    expect(request.url.searchParams.get('tab')).toBe('all');
    expect(request.url.searchParams.get('limit')).toBe('10');
    expect(request.url.searchParams.get('offset')).toBe('20');
    expect(request.init.credentials).toBeUndefined();

    await expect(api.getCollectProfile('COLLECT1')).rejects.toMatchObject({
      name: 'ApiError', status: 403, message: 'Collection is closed', detail: 'Collection is closed',
    });
    request = lastRequest();
    expect(request.init.credentials).toBe('include');

    await expect(api.getCollectMyPicks('COLLECT1')).rejects.toMatchObject({
      name: 'ApiError', status: 403, message: 'Verify your email', code: 'email_verification_required',
    });
    request = lastRequest();
    expect(request.init.credentials).toBe('include');

    await expect(api.getCollectPreview('COLLECT1', 17)).rejects.toMatchObject({
      name: 'ApiError', status: 404, message: 'Request not found', detail: 'Request not found',
    });
    request = lastRequest();
    expect(request.url.pathname).toBe('/api/public/collect/COLLECT1/requests/17/preview');
    expect(request.init.credentials).toBe('include');
  });

  it('uses the shared public error fallback when a collection error body is empty', async () => {
    fetchMock.mockResolvedValueOnce(new Response('', { status: 502 }));

    await expect(api.getCollectEvent('COLLECT1')).rejects.toMatchObject({
      name: 'ApiError', status: 502, message: 'Request failed',
    });
  });

  // Regression for baseline 57cfcdc6867f: kiosk and guest errors lost structured API details.
  it('uses consistent API errors across kiosk, collection, and guest verification calls', async () => {
    fetchMock
      .mockResolvedValueOnce(response({ detail: 'Pair challenge expired' }, 410))
      .mockResolvedValueOnce(response({ detail: { code: 'pairing_denied', message: 'Pairing denied' } }, 403))
      .mockResolvedValueOnce(response({ detail: { code: 'kiosk_session_invalid', message: 'Session expired' } }, 401))
      .mockResolvedValueOnce(response({ detail: 'Nickname is invalid' }, 422))
      .mockResolvedValueOnce(response({ detail: { code: 'rate_limited', message: 'Try again later' } }, 429))
      .mockResolvedValueOnce(new Response('', { status: 500 }))
      .mockResolvedValueOnce(response({ detail: { code: 'duplicate_request', message: 'Already submitted' } }, 409))
      .mockResolvedValueOnce(response({ detail: 'You cannot vote for your own request' }, 403));

    await expect(api.getKioskPairChallenge()).rejects.toMatchObject({
      name: 'ApiError', status: 410, message: 'Pair challenge expired', detail: 'Pair challenge expired',
    });
    let request = lastRequest();
    expect(request.url.pathname).toBe('/api/public/kiosk/pair-challenge');
    expect(request.init.method).toBeUndefined();
    expect(request.init.credentials).toBe('include');

    await expect(api.createKioskPairing('nonce')).rejects.toMatchObject({
      name: 'ApiError', status: 403, message: 'Pairing denied', code: 'pairing_denied',
    });
    request = lastRequest();
    expect(request.url.pathname).toBe('/api/public/kiosk/pair');
    expect(request.init.method).toBe('POST');
    expect(new Headers(request.init.headers).get('X-Pair-Nonce')).toBe('nonce');
    expect(request.init.credentials).toBe('include');

    const sessionToken = 'session-secret';
    await expect(api.getKioskAssignment(sessionToken)).rejects.toMatchObject({
      name: 'ApiError', status: 401, message: 'Session expired', code: 'kiosk_session_invalid',
    });
    request = lastRequest();
    expect(request.url.pathname).toBe('/api/public/kiosk/session/assignment');
    expect(request.url.href).not.toContain(sessionToken);
    expect(new Headers(request.init.headers).get('X-Kiosk-Session')).toBe(sessionToken);
    expect(request.init.credentials).toBeUndefined();

    await expect(api.setCollectProfile('COLLECT1', { nickname: 'Bad Name' })).rejects.toMatchObject({
      name: 'ApiError', status: 422, message: 'Nickname is invalid',
    });

    await expect(api.requestVerificationCode('guest@example.com', 'turnstile')).rejects.toMatchObject({
      name: 'ApiError', status: 429, message: 'Try again later', code: 'rate_limited',
    });
    expect(lastRequest().init.credentials).toBe('include');

    await expect(api.confirmVerificationCode('guest@example.com', '000000')).rejects.toMatchObject({
      name: 'ApiError', status: 500, message: 'Verification failed',
    });
    expect(lastRequest().init.credentials).toBe('include');

    await expect(api.submitCollectRequest('COLLECT1', {
      song_title: 'Song', artist: 'Artist', source: 'manual',
    })).rejects.toMatchObject({
      name: 'ApiError', status: 409, message: 'Already submitted', code: 'duplicate_request',
    });

    await expect(api.voteCollectRequest('COLLECT1', 17)).rejects.toMatchObject({
      name: 'ApiError', status: 403, message: 'You cannot vote for your own request',
    });
  });

  it('keeps the set-profile human verification retry response and credentials', async () => {
    fetchMock
      .mockResolvedValueOnce(response({ detail: { code: 'human_verification_required' } }, 403))
      .mockResolvedValueOnce(response({ nickname: 'DJ', email_verified: false, submission_count: 0, submission_cap: 15 }));
    const reverify = vi.fn().mockResolvedValue(undefined);

    await expect(api.setCollectProfile('COLLECT1', { nickname: 'DJ' }, reverify))
      .resolves.toMatchObject({ nickname: 'DJ' });

    expect(reverify).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const [, init] of fetchMock.mock.calls) {
      expect(init?.credentials).toBe('include');
      expect(JSON.parse(String(init?.body))).toEqual({ nickname: 'DJ' });
    }
  });
});
