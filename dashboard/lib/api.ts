import type {
  AdminEvent,
  AdminUser,
  AIModelsResponse,
  AISettings,
  AISettingsUpdate,
  ActivityLogEntry,
  ArchivedEvent,
  BeatportEventSettings,
  BeatportSearchResult,
  BeatportStatus,
  BridgeCommandResponse,
  DisplaySettingsResponse,
  PublicBridgeStatus,
  Event,
  GuestRequestListResponse,
  HasRequestedResponse,
  IntegrationCheckResponse,
  IntegrationHealthResponse,
  IntegrationToggleResponse,
  KioskDisplay,
  KioskInfo,
  KioskPairResponse,
  KioskPairStatusResponse,
  KioskSessionResponse,
  LLMRecommendationResponse,
  MyRequestsResponse,
  NowPlayingInfo,
  PaginatedResponse,
  PlayHistoryResponse,
  PlaylistListResponse,
  RecommendationResponse,
  SearchResult,
  SongRequest,
  SystemSettings,
  SystemStats,
  TidalEventSettings,
  TidalSearchResult,
  TidalSyncResult,
  TidalStatus,
  VoteResponse,
} from './api-types';

export type {
  ActivityLogEntry,
  AdminEvent,
  AdminUser,
  AIModelInfo,
  AIModelsResponse,
  AISettings,
  AISettingsUpdate,
  ArchivedEvent,
  BeatportEventSettings,
  BeatportSearchResult,
  BeatportStatus,
  BridgeCommandResponse,
  BridgeEnrichedStatus,
  CapabilityStatus,
  DisplaySettingsResponse,
  Event,
  EventMusicProfile,
  GuestNowPlaying,
  GuestRequestInfo,
  GuestRequestListResponse,
  HasRequestedResponse,
  IntegrationCheckResponse,
  IntegrationHealthResponse,
  IntegrationServiceStatus,
  IntegrationToggleResponse,
  KioskDisplay,
  KioskInfo,
  KioskPairResponse,
  KioskPairStatusResponse,
  KioskSessionResponse,
  LLMQueryInfo,
  LLMRecommendationResponse,
  MyRequestInfo,
  MyRequestsResponse,
  NowPlayingInfo,
  PaginatedResponse,
  PlayHistoryItem,
  PlayHistoryResponse,
  PublicBridgeStatus,
  PublicRequestInfo,
  RecommendationResponse,
  RecommendedTrack,
  SearchResult,
  ServiceCapabilities,
  SongRequest,
  SyncResultEntry,
  SystemSettings,
  SystemStats,
  TidalEventSettings,
  TidalSearchResult,
  TidalSyncResult,
  TidalStatus,
  VoteResponse,
} from './api-types';

// ========== Pre-Event Collection Types ==========

export interface CollectEventPreview {
  code: string;
  name: string;
  banner_filename: string | null;
  banner_url: string | null;
  banner_colors: string[] | null;
  submission_cap_per_guest: number;
  registration_enabled: boolean;
  phase: 'pre_announce' | 'collection' | 'live' | 'closed';
  collection_opens_at: string | null;
  live_starts_at: string | null;
  expires_at: string;
}

export interface CollectLeaderboardRow {
  id: number;
  title: string;
  artist: string;
  artwork_url: string | null;
  vote_count: number;
  nickname: string | null;
  status: 'new' | 'accepted' | 'playing' | 'played' | 'rejected';
  created_at: string;
  bpm?: number | null;
  musical_key?: string | null;
  genre?: string | null;
  requester_verified?: boolean;
}

export interface CollectLeaderboardResponse {
  requests: CollectLeaderboardRow[];
  total: number;
}

export interface CollectProfileResponse {
  nickname: string | null;
  email_verified: boolean;
  submission_count: number;
  submission_cap: number;
}

export interface CollectMyPicksItem extends CollectLeaderboardRow {
  interaction: 'submitted' | 'upvoted';
}

export interface CollectMyPicksResponse {
  submitted: CollectMyPicksItem[];
  upvoted: CollectMyPicksItem[];
  is_top_contributor: boolean;
  first_suggestion_ids: number[];
  voted_request_ids: number[];
}

export interface CollectPreviewResponse {
  source: 'spotify' | 'tidal' | 'beatport' | 'manual';
  source_url: string | null;
}

export interface CollectionSettingsResponse {
  collection_opens_at: string | null;
  live_starts_at: string | null;
  submission_cap_per_guest: number;
  collection_phase_override: 'force_collection' | 'force_live' | null;
  phase: 'pre_announce' | 'collection' | 'live' | 'closed';
  tidal_sync_enabled: boolean;
  tidal_collection_playlist_id: string | null;
  tidal_collection_bidirectional: boolean;
}

export interface CollectionSyncResponse {
  queued: number;
}

export interface PendingReviewRow {
  id: number;
  song_title: string;
  artist: string;
  artwork_url: string | null;
  vote_count: number;
  nickname: string | null;
  created_at: string;
  note: string | null;
  status: 'new' | 'accepted' | 'playing' | 'played' | 'rejected';
}

export interface PendingReviewResponse {
  requests: PendingReviewRow[];
  total: number;
}

export interface BulkReviewResponse {
  accepted: number;
  rejected: number;
  unchanged: number;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export class NicknameConflictError extends Error {
  claimed: boolean;
  constructor(claimed: boolean) {
    super('nickname_taken');
    this.name = 'NicknameConflictError';
    this.claimed = claimed;
  }
}

export class HumanVerificationRequiredError extends ApiError {
  constructor() {
    super('Human verification required', 403);
    this.name = 'HumanVerificationRequiredError';
  }
}

/**
 * Wrap a guest-public fetch in 403-human-verification-required retry logic.
 * Caller passes a `reverify` async function that re-runs the Turnstile
 * bootstrap and resolves once `wrzdj_human` cookie is set. On a 403 with
 * `detail.code === 'human_verification_required'`, the wrapper calls
 * `reverify()` and retries the fetch once.
 */
export class EmailVerificationRequiredError extends Error {
  constructor() {
    super('email_verification_required');
    this.name = 'EmailVerificationRequiredError';
  }
}

export async function withHumanRetry<T>(
  doFetch: () => Promise<Response>,
  reverify: () => Promise<void>,
): Promise<T> {
  let res = await doFetch();
  if (res.status === 403) {
    const body = await res.clone().json().catch(() => null);
    if (body?.detail?.code === 'human_verification_required') {
      await reverify();
      res = await doFetch();
    } else if (body?.detail?.code === 'email_verification_required') {
      throw new EmailVerificationRequiredError();
    }
  }
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Request failed' }));
    throw new ApiError(error.detail || 'Request failed', res.status);
  }
  return res.json();
}

function getApiUrl(): string {
  // Use explicit env var if set
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL;
  }
  // In browser, use same hostname as the page (for LAN access)
  if (typeof window !== 'undefined') {
    return `http://${window.location.hostname}:8000`;
  }
  // SSR fallback
  return 'http://localhost:8000';
}

class ApiClient {
  private token: string | null = null;
  private onUnauthorized: (() => void) | null = null;

  setToken(token: string | null) {
    this.token = token;
  }

  /**
   * Register a callback for 401 responses on authenticated endpoints.
   * Used by AuthProvider to auto-logout on token expiration.
   */
  setUnauthorizedHandler(handler: (() => void) | null) {
    this.onUnauthorized = handler;
  }

  private async fetch<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers = new Headers({
      'Content-Type': 'application/json',
    });

    if (options.headers) {
      new Headers(options.headers).forEach((value, key) => {
        headers.set(key, value);
      });
    }

    if (this.token) {
      headers.set('Authorization', `Bearer ${this.token}`);
    }

    const response = await fetch(`${getApiUrl()}${path}`, {
      ...options,
      headers,
    });

    if (!response.ok) {
      if (response.status === 401 && this.onUnauthorized) {
        this.onUnauthorized();
      }
      const error = await response.json().catch(() => ({ detail: 'Request failed' }));
      throw new ApiError(error.detail || 'Request failed', response.status);
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return response.json();
  }

  /**
   * Make an authenticated raw fetch (no JSON content-type, no JSON parsing).
   * Returns the raw Response. Handles 401 → onUnauthorized.
   */
  private async rawFetch(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    if (this.token) {
      headers.set('Authorization', `Bearer ${this.token}`);
    }

    const url = path.startsWith('http') ? path : `${getApiUrl()}${path}`;
    const response = await fetch(url, { ...init, headers });

    if (!response.ok) {
      if (response.status === 401 && this.onUnauthorized) {
        this.onUnauthorized();
      }
      const error = await response.json().catch(() => ({ detail: 'Request failed' }));
      throw new ApiError(error.detail || 'Request failed', response.status);
    }

    return response;
  }

  /**
   * Fetch a public (no-auth) endpoint and parse JSON response.
   * Throws ApiError on non-OK responses.
   */
  private async publicFetch<T>(url: string): Promise<T> {
    const response = await fetch(url);
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Request failed' }));
      throw new ApiError(error.detail || 'Request failed', response.status);
    }
    return response.json();
  }

  /**
   * Download a CSV blob from an authenticated endpoint and trigger browser download.
   * Parses filename from Content-Disposition header, falling back to the provided default.
   */
  private async downloadCsvBlob(url: string, defaultFilename: string): Promise<void> {
    const response = await this.rawFetch(url);
    const blob = await response.blob();
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    const contentDisposition = response.headers.get('Content-Disposition');
    const filenameMatch = contentDisposition?.match(/filename=([^;]+)/);
    a.download = filenameMatch ? filenameMatch[1].replace(/"/g, '') : defaultFilename;
    a.click();
    URL.revokeObjectURL(blobUrl);
  }

  async login(username: string, password: string): Promise<{ access_token: string }> {
    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);

    const response = await fetch(`${getApiUrl()}/api/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: formData,
    });

    if (!response.ok) {
      if (response.status === 401) {
        throw new Error('Invalid credentials');
      } else if (response.status === 429) {
        throw new Error('Too many attempts. Try again later.');
      }
      throw new Error('Login failed. Please try again.');
    }

    return response.json();
  }

  async getMe(): Promise<{
    id: number;
    username: string;
    role: string;
    help_pages_seen: string[];
    pending_email: string | null;
    email: string | null;
  }> {
    return this.fetch('/api/auth/me');
  }

  async markHelpPageSeen(page: string): Promise<void> {
    await this.fetch('/api/auth/help-seen', {
      method: 'POST',
      body: JSON.stringify({ page }),
    });
  }

  async changePassword(data: {
    current_password: string;
    new_password: string;
    confirm_new_password: string;
  }): Promise<{ status: string; message: string }> {
    return this.fetch('/api/auth/me/password', {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async requestEmailChange(data: {
    current_password: string;
    new_email: string;
  }): Promise<{ status: string; message: string }> {
    return this.fetch('/api/auth/me/email/request', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async confirmEmailChange(token: string): Promise<{ status: string; message: string }> {
    return this.publicFetch(
      `${getApiUrl()}/api/auth/email/confirm?token=${encodeURIComponent(token)}`
    );
  }

  async getPublicSettings(): Promise<{ registration_enabled: boolean; turnstile_site_key: string }> {
    return this.publicFetch(`${getApiUrl()}/api/auth/settings`);
  }

  async verifyHuman(turnstileToken: string): Promise<{ verified: boolean; expires_in: number }> {
    const res = await fetch(`${getApiUrl()}/api/public/guest/verify-human`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ turnstile_token: turnstileToken }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: 'Request failed' }));
      throw new ApiError(error.detail || 'Verify failed', res.status);
    }
    return res.json();
  }

  // Fast-path probe used by useHumanVerification on page mount. Returns
  // verified=false on any error (network, 5xx) so the caller's fallback to
  // running Turnstile is unconditional and simple.
  async getVerifyStatus(): Promise<{ verified: boolean; expires_in: number }> {
    try {
      const res = await fetch(`${getApiUrl()}/api/public/guest/verify-status`, {
        method: 'GET',
        credentials: 'include',
      });
      if (!res.ok) return { verified: false, expires_in: 0 };
      // Await JSON parse INSIDE the try so a parse failure falls into the
      // catch and still satisfies the fail-closed {verified: false} contract.
      return await res.json();
    } catch {
      return { verified: false, expires_in: 0 };
    }
  }

  // Gated endpoint returning the live event join_code to verified humans.
  // Throws ApiError on non-2xx because callers discriminate 403 (re-verify)
  // from 409 (phase mismatch — keep polling).
  async getLiveJoinCode(code: string): Promise<{ join_code: string }> {
    const res = await fetch(
      `${getApiUrl()}/api/public/collect/${code}/live-join-code`,
      { method: 'GET', credentials: 'include' },
    );
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: 'Request failed' }));
      throw new ApiError(
        typeof body.detail === 'string' ? body.detail : 'Live join code unavailable',
        res.status,
      );
    }
    return res.json();
  }

  async register(data: {
    username: string;
    email: string;
    password: string;
    confirm_password: string;
    turnstile_token: string;
  }): Promise<{ status: string; message: string }> {
    const response = await fetch(`${getApiUrl()}/api/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Registration failed' }));
      throw new ApiError(error.detail || 'Registration failed', response.status);
    }
    return response.json();
  }

  async getEvents(): Promise<Event[]> {
    return this.fetch('/api/events');
  }

  async createEvent(name: string, expiresHours: number = 6): Promise<Event> {
    return this.fetch('/api/events', {
      method: 'POST',
      body: JSON.stringify({ name, expires_hours: expiresHours }),
    });
  }

  async getEvent(code: string): Promise<Event> {
    return this.fetch(`/api/events/${code}`);
  }

  async updateEvent(code: string, data: { expires_at?: string; name?: string }): Promise<Event> {
    return this.fetch(`/api/events/${code}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async deleteEvent(code: string): Promise<void> {
    await this.rawFetch(`/api/events/${code}`, { method: 'DELETE' });
  }

  async bulkDeleteEvents(codes: string[]): Promise<{ status: string; count: number }> {
    return this.fetch('/api/events/bulk-delete', {
      method: 'POST',
      body: JSON.stringify({ codes }),
    });
  }

  async getRequests(
    code: string,
    options?: { status?: string; sort?: 'chronological' | 'priority' },
  ): Promise<SongRequest[]> {
    const params = new URLSearchParams();
    if (options?.status) params.set('status', options.status);
    if (options?.sort) params.set('sort', options.sort);
    const qs = params.toString();
    return this.fetch(`/api/events/${code}/requests${qs ? `?${qs}` : ''}`);
  }

  async acceptAllRequests(code: string): Promise<{ status: string; accepted_count: number }> {
    return this.fetch(`/api/events/${code}/requests/accept-all`, {
      method: 'POST',
    });
  }

  async rejectAllRequests(code: string): Promise<{ status: string; count: number }> {
    return this.fetch(`/api/events/${code}/requests/reject-all`, {
      method: 'POST',
    });
  }

  async bulkDeleteRequests(code: string, status?: string): Promise<{ status: string; count: number }> {
    const params = status ? `?status=${status}` : '';
    return this.fetch(`/api/events/${code}/requests/bulk${params}`, {
      method: 'DELETE',
    });
  }

  async updateRequestStatus(requestId: number, status: string): Promise<SongRequest> {
    return this.fetch(`/api/requests/${requestId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
  }

  async deleteRequest(requestId: number): Promise<void> {
    return this.fetch(`/api/requests/${requestId}`, { method: 'DELETE' });
  }

  async refreshRequestMetadata(requestId: number): Promise<SongRequest> {
    return this.fetch(`/api/requests/${requestId}/refresh-metadata`, {
      method: 'POST',
    });
  }

  async enrichAllRequests(code: string): Promise<{ queued: number; remaining: number }> {
    return this.fetch(`/api/events/${encodeURIComponent(code)}/enrich-all`, {
      method: 'POST',
    });
  }

  async submitRequest(
    code: string,
    artist: string,
    title: string,
    note?: string,
    sourceUrl?: string,
    artworkUrl?: string,
    rawSearchQuery?: string,
    metadata?: { source?: string; genre?: string; bpm?: number; musical_key?: string },
    source?: string,
    nickname?: string,
    reverify?: () => Promise<void>,
  ): Promise<SongRequest> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (this.token) headers['Authorization'] = `Bearer ${this.token}`;
    const doFetch = () =>
      fetch(`${getApiUrl()}/api/events/${code}/requests`, {
        method: 'POST',
        headers,
        credentials: 'include',
        body: JSON.stringify({
          artist,
          title,
          note,
          nickname,
          source: metadata?.source ?? source ?? 'spotify',
          source_url: sourceUrl,
          artwork_url: artworkUrl,
          raw_search_query: rawSearchQuery,
          genre: metadata?.genre,
          bpm: metadata?.bpm,
          musical_key: metadata?.musical_key,
        }),
      });
    if (reverify) {
      return withHumanRetry<SongRequest>(doFetch, reverify);
    }
    const res = await doFetch();
    if (!res.ok) {
      if (res.status === 401 && this.onUnauthorized) {
        this.onUnauthorized();
      }
      const body = await res.json().catch(() => ({}));
      throw new ApiError((body as { detail?: string }).detail ?? 'Submit failed', res.status);
    }
    return res.json();
  }

  async search(query: string): Promise<SearchResult[]> {
    return this.fetch(`/api/search?q=${encodeURIComponent(query)}`);
  }

  async eventSearch(
    code: string,
    query: string,
    reverify?: () => Promise<void>,
  ): Promise<SearchResult[]> {
    const doFetch = () =>
      fetch(`${getApiUrl()}/api/events/${code}/search?q=${encodeURIComponent(query)}`, {
        credentials: 'include',
      });
    if (reverify) {
      return withHumanRetry<SearchResult[]>(doFetch, reverify);
    }
    const res = await doFetch();
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: 'Request failed' }));
      throw new ApiError(error.detail || 'Request failed', res.status);
    }
    return res.json();
  }

  async voteRequest(requestId: number): Promise<VoteResponse> {
    return this.fetch(`/api/requests/${requestId}/vote`, { method: 'POST' });
  }

  async unvoteRequest(requestId: number): Promise<VoteResponse> {
    return this.fetch(`/api/requests/${requestId}/vote`, { method: 'DELETE' });
  }

  async publicVoteRequest(
    requestId: number,
    reverify?: () => Promise<void>,
  ): Promise<VoteResponse> {
    const doFetch = () =>
      fetch(`${getApiUrl()}/api/requests/${requestId}/vote`, {
        method: 'POST',
        credentials: 'include',
      });
    if (reverify) {
      return withHumanRetry<VoteResponse>(doFetch, reverify);
    }
    const res = await doFetch();
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: 'Vote failed' }));
      throw new ApiError(error.detail || 'Vote failed', res.status);
    }
    return res.json();
  }

  async getArchivedEvents(): Promise<ArchivedEvent[]> {
    return this.fetch('/api/events/archived');
  }

  async exportEventCsv(code: string): Promise<void> {
    return this.downloadCsvBlob(
      `${getApiUrl()}/api/events/${code}/export/csv`,
      `${code}.csv`
    );
  }

  async exportPlayHistoryCsv(code: string): Promise<void> {
    return this.downloadCsvBlob(
      `${getApiUrl()}/api/events/${code}/export/play-history/csv`,
      `${code}_play_history.csv`
    );
  }

  async checkHasRequested(code: string): Promise<HasRequestedResponse> {
    const res = await fetch(`${getApiUrl()}/api/public/events/${code}/has-requested`, {
      credentials: 'include',
    });
    if (!res.ok) throw new ApiError(`checkHasRequested failed: ${res.status}`, res.status);
    return res.json();
  }

  async getMyRequests(code: string): Promise<MyRequestsResponse> {
    const res = await fetch(`${getApiUrl()}/api/public/events/${code}/my-requests`, {
      credentials: 'include',
    });
    if (!res.ok) throw new ApiError(`getMyRequests failed: ${res.status}`, res.status);
    return res.json();
  }

  async getPublicRequests(code: string): Promise<GuestRequestListResponse> {
    return this.publicFetch(`${getApiUrl()}/api/public/events/${code}/requests`);
  }

  async getKioskDisplay(code: string): Promise<KioskDisplay> {
    return this.publicFetch(`${getApiUrl()}/api/public/events/${code}/display`);
  }

  /**
   * Get current now-playing track from StageLinQ.
   * Returns null if no track is playing.
   */
  async getNowPlaying(code: string): Promise<NowPlayingInfo | null> {
    const response = await fetch(`${getApiUrl()}/api/public/e/${code}/nowplaying`);
    if (!response.ok) {
      if (response.status === 404 || response.status === 410) {
        throw new ApiError('Event not found', response.status);
      }
      return null;
    }
    const data = await response.json();
    return data || null;
  }

  /**
   * Get bridge connection status (independent of track data).
   */
  async getBridgeStatus(code: string): Promise<PublicBridgeStatus> {
    return this.publicFetch(`${getApiUrl()}/api/public/e/${code}/bridge-status`);
  }

  /**
   * Get play history for an event.
   */
  async getPlayHistory(code: string, limit: number = 100, offset: number = 0): Promise<PlayHistoryResponse> {
    return this.publicFetch(
      `${getApiUrl()}/api/public/e/${code}/history?limit=${limit}&offset=${offset}`
    );
  }

  /**
   * Set now playing visibility on kiosk display.
   * When hidden=true, the now playing section will be hidden on the kiosk.
   * When hidden=false, the now playing section will be shown and the auto-hide timer resets.
   */
  async setNowPlayingVisibility(
    code: string,
    hidden: boolean,
    autoHideMinutes?: number,
  ): Promise<DisplaySettingsResponse> {
    const body: Record<string, unknown> = { now_playing_hidden: hidden };
    if (autoHideMinutes !== undefined) {
      body.now_playing_auto_hide_minutes = autoHideMinutes;
    }
    return this.fetch(`/api/events/${code}/display-settings`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  }

  /**
   * Update only the auto-hide timeout without affecting visibility state.
   */
  async setAutoHideMinutes(code: string, minutes: number): Promise<DisplaySettingsResponse> {
    return this.fetch(`/api/events/${code}/display-settings`, {
      method: 'PATCH',
      body: JSON.stringify({ now_playing_auto_hide_minutes: minutes }),
    });
  }

  /**
   * Get current display settings for an event.
   */
  async getDisplaySettings(code: string): Promise<DisplaySettingsResponse> {
    return this.fetch(`/api/events/${code}/display-settings`);
  }

  /**
   * Open or close song requests for an event.
   */
  async setRequestsOpen(code: string, open: boolean): Promise<DisplaySettingsResponse> {
    return this.fetch(`/api/events/${code}/display-settings`, {
      method: 'PATCH',
      body: JSON.stringify({ requests_open: open }),
    });
  }

  /**
   * Toggle kiosk display-only mode.
   */
  async setKioskDisplayOnly(code: string, displayOnly: boolean): Promise<DisplaySettingsResponse> {
    return this.fetch(`/api/events/${code}/display-settings`, {
      method: 'PATCH',
      body: JSON.stringify({ kiosk_display_only: displayOnly }),
    });
  }

  // ========== Tidal Integration ==========

  /**
   * Get Tidal account status for current user.
   */
  async getTidalStatus(): Promise<TidalStatus> {
    return this.fetch('/api/tidal/status');
  }

  /**
   * Start Tidal device login flow.
   * Returns URL and code for user to visit.
   */
  async startTidalAuth(): Promise<{ verification_url: string; user_code: string; message: string }> {
    return this.fetch('/api/tidal/auth/start', { method: 'POST' });
  }

  /**
   * Check if Tidal device login is complete.
   */
  async checkTidalAuth(): Promise<{ complete: boolean; pending?: boolean; error?: string; verification_url?: string; user_code?: string; user_id?: string }> {
    return this.fetch('/api/tidal/auth/check');
  }

  /**
   * Cancel pending Tidal device login.
   */
  async cancelTidalAuth(): Promise<{ status: string; message: string }> {
    return this.fetch('/api/tidal/auth/cancel', { method: 'POST' });
  }

  /**
   * Disconnect Tidal account.
   */
  async disconnectTidal(): Promise<{ status: string; message: string }> {
    return this.fetch('/api/tidal/disconnect', { method: 'POST' });
  }

  /**
   * Get Tidal sync settings for an event.
   */
  async getTidalEventSettings(eventId: number): Promise<TidalEventSettings> {
    return this.fetch(`/api/tidal/events/${eventId}/settings`);
  }

  /**
   * Update Tidal sync settings for an event.
   */
  async updateTidalEventSettings(
    eventId: number,
    settings: { tidal_sync_enabled: boolean }
  ): Promise<TidalEventSettings> {
    return this.fetch(`/api/tidal/events/${eventId}/settings`, {
      method: 'PUT',
      body: JSON.stringify(settings),
    });
  }

  /**
   * Search Tidal for tracks (for manual linking).
   */
  async searchTidal(query: string, limit: number = 10): Promise<TidalSearchResult[]> {
    return this.fetch(`/api/tidal/search?q=${encodeURIComponent(query)}&limit=${limit}`);
  }

  /**
   * Manually sync a request to Tidal.
   */
  async syncRequestToTidal(requestId: number): Promise<TidalSyncResult> {
    return this.fetch(`/api/tidal/requests/${requestId}/sync`, { method: 'POST' });
  }

  /**
   * Manually link a Tidal track to a request.
   */
  async linkTidalTrack(requestId: number, tidalTrackId: string): Promise<TidalSyncResult> {
    return this.fetch(`/api/tidal/requests/${requestId}/link`, {
      method: 'POST',
      body: JSON.stringify({ tidal_track_id: tidalTrackId }),
    });
  }
  // ========== Beatport Integration ==========

  async getBeatportStatus(): Promise<BeatportStatus> {
    return this.fetch('/api/beatport/status');
  }

  async loginBeatport(username: string, password: string): Promise<{ status: string; message: string }> {
    return this.fetch('/api/beatport/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
  }

  async disconnectBeatport(): Promise<{ status: string; message: string }> {
    return this.fetch('/api/beatport/disconnect', { method: 'POST' });
  }

  async getBeatportEventSettings(eventId: number): Promise<BeatportEventSettings> {
    return this.fetch(`/api/beatport/events/${eventId}/settings`);
  }

  async updateBeatportEventSettings(
    eventId: number,
    settings: { beatport_sync_enabled: boolean }
  ): Promise<BeatportEventSettings> {
    return this.fetch(`/api/beatport/events/${eventId}/settings`, {
      method: 'PUT',
      body: JSON.stringify(settings),
    });
  }

  async searchBeatport(query: string, limit: number = 10): Promise<BeatportSearchResult[]> {
    return this.fetch(`/api/beatport/search?q=${encodeURIComponent(query)}&limit=${limit}`);
  }

  async linkBeatportTrack(requestId: number, beatportTrackId: string): Promise<{ status: string }> {
    return this.fetch(`/api/beatport/requests/${requestId}/link`, {
      method: 'POST',
      body: JSON.stringify({ beatport_track_id: beatportTrackId }),
    });
  }

  // ========== Recommendations ==========

  async generateRecommendations(code: string): Promise<RecommendationResponse> {
    return this.fetch(`/api/events/${code}/recommendations`, {
      method: 'POST',
    });
  }

  async getEventPlaylists(code: string): Promise<PlaylistListResponse> {
    return this.fetch(`/api/events/${code}/playlists`);
  }

  async generateLLMRecommendations(code: string, prompt: string): Promise<LLMRecommendationResponse> {
    return this.fetch(`/api/events/${code}/recommendations/llm`, {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    });
  }

  async generateRecommendationsFromTemplate(
    code: string, source: string, playlistId: string
  ): Promise<RecommendationResponse> {
    return this.fetch(`/api/events/${code}/recommendations/from-template`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, playlist_id: playlistId }),
    });
  }

  // ========== Banner ==========

  async uploadEventBanner(code: string, file: File): Promise<Event> {
    const formData = new FormData();
    formData.append('file', file);
    // Do NOT set Content-Type — browser sets it with multipart boundary
    const response = await this.rawFetch(`/api/events/${code}/banner`, {
      method: 'POST',
      body: formData,
    });
    return response.json();
  }

  async deleteEventBanner(code: string): Promise<Event> {
    return this.fetch(`/api/events/${code}/banner`, { method: 'DELETE' });
  }

  // ========== Admin ==========

  async getAdminStats(): Promise<SystemStats> {
    return this.fetch('/api/admin/stats');
  }

  async getAdminUsers(
    page: number = 1,
    limit: number = 20,
    role?: string
  ): Promise<PaginatedResponse<AdminUser>> {
    const params = new URLSearchParams({ page: String(page), limit: String(limit) });
    if (role) params.set('role', role);
    return this.fetch(`/api/admin/users?${params}`);
  }

  async createAdminUser(data: {
    username: string;
    password: string;
    role: string;
  }): Promise<AdminUser> {
    return this.fetch('/api/admin/users', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updateAdminUser(
    userId: number,
    data: { role?: string; is_active?: boolean; password?: string }
  ): Promise<AdminUser> {
    return this.fetch(`/api/admin/users/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async deleteAdminUser(userId: number): Promise<void> {
    await this.fetch(`/api/admin/users/${userId}`, { method: 'DELETE' });
  }

  async getAdminEvents(
    page: number = 1,
    limit: number = 20
  ): Promise<PaginatedResponse<AdminEvent>> {
    return this.fetch(`/api/admin/events?page=${page}&limit=${limit}`);
  }

  async updateAdminEvent(
    code: string,
    data: { name?: string; expires_at?: string }
  ): Promise<AdminEvent> {
    return this.fetch(`/api/admin/events/${code}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async deleteAdminEvent(code: string): Promise<void> {
    await this.fetch(`/api/admin/events/${code}`, { method: 'DELETE' });
  }

  async bulkDeleteAdminEvents(codes: string[]): Promise<{ status: string; count: number }> {
    return this.fetch('/api/admin/events/bulk-delete', {
      method: 'POST',
      body: JSON.stringify({ codes }),
    });
  }

  async getAdminSettings(): Promise<SystemSettings> {
    return this.fetch('/api/admin/settings');
  }

  async updateAdminSettings(data: Partial<SystemSettings>): Promise<SystemSettings> {
    return this.fetch('/api/admin/settings', {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  // ========== Admin Integrations ==========

  async getIntegrations(): Promise<IntegrationHealthResponse> {
    return this.fetch('/api/admin/integrations');
  }

  async toggleIntegration(
    service: string,
    enabled: boolean
  ): Promise<IntegrationToggleResponse> {
    return this.fetch(`/api/admin/integrations/${service}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    });
  }

  async checkIntegrationHealth(
    service: string
  ): Promise<IntegrationCheckResponse> {
    return this.fetch(`/api/admin/integrations/${service}/check`, {
      method: 'POST',
    });
  }

  // ========== Admin AI Settings ==========

  async getAIModels(): Promise<AIModelsResponse> {
    return this.fetch('/api/admin/ai/models');
  }

  async getAISettings(): Promise<AISettings> {
    return this.fetch('/api/admin/ai/settings');
  }

  async updateAISettings(data: AISettingsUpdate): Promise<AISettings> {
    return this.fetch('/api/admin/ai/settings', {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  // ========== Kiosk Pairing ==========

  async getKioskPairChallenge(): Promise<{ nonce: string; expires_in: number }> {
    const response = await fetch(`${getApiUrl()}/api/public/kiosk/pair-challenge`, {
      credentials: 'include',
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Failed to fetch pair challenge' }));
      throw new ApiError(error.detail || 'Failed to fetch pair challenge', response.status);
    }
    return response.json();
  }

  async createKioskPairing(nonce: string): Promise<KioskPairResponse> {
    const response = await fetch(`${getApiUrl()}/api/public/kiosk/pair`, {
      method: 'POST',
      headers: { 'X-Pair-Nonce': nonce },
      credentials: 'include',
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Pairing failed' }));
      throw new ApiError(error.detail || 'Pairing failed', response.status);
    }
    return response.json();
  }

  async getKioskPairStatus(pairCode: string): Promise<KioskPairStatusResponse> {
    return this.publicFetch(`${getApiUrl()}/api/public/kiosk/pair/${pairCode}/status`);
  }

  async getKioskAssignment(sessionToken: string): Promise<KioskSessionResponse> {
    const response = await fetch(`${getApiUrl()}/api/public/kiosk/session/assignment`, {
      headers: { 'X-Kiosk-Session': sessionToken },
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Request failed' }));
      throw new ApiError(error.detail || 'Request failed', response.status);
    }
    return response.json();
  }

  async completeKioskPairing(
    pairCode: string,
    eventCode: string
  ): Promise<KioskInfo> {
    return this.fetch(`/api/kiosk/pair/${pairCode}/complete`, {
      method: 'POST',
      body: JSON.stringify({ event_code: eventCode }),
    });
  }

  async getMyKiosks(): Promise<KioskInfo[]> {
    return this.fetch('/api/kiosk/mine');
  }

  async assignKiosk(kioskId: number, eventCode: string): Promise<KioskInfo> {
    return this.fetch(`/api/kiosk/${kioskId}/assign`, {
      method: 'PATCH',
      body: JSON.stringify({ event_code: eventCode }),
    });
  }

  async renameKiosk(kioskId: number, name: string | null): Promise<KioskInfo> {
    return this.fetch(`/api/kiosk/${kioskId}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    });
  }

  async deleteKiosk(kioskId: number): Promise<void> {
    return this.fetch(`/api/kiosk/${kioskId}`, { method: 'DELETE' });
  }

  // ========== Pre-Event Collection (Public) ==========

  async getCollectEvent(code: string): Promise<CollectEventPreview> {
    const res = await fetch(`${getApiUrl()}/api/public/collect/${code}`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) throw new ApiError(`getCollectEvent failed: ${res.status}`, res.status);
    return res.json();
  }

  async getCollectLeaderboard(
    code: string,
    tab: 'trending' | 'all' = 'trending',
  ): Promise<CollectLeaderboardResponse> {
    const res = await fetch(
      `${getApiUrl()}/api/public/collect/${code}/leaderboard?tab=${tab}`,
      { method: 'GET', headers: { 'Content-Type': 'application/json' } },
    );
    if (!res.ok) throw new ApiError(`getCollectLeaderboard failed: ${res.status}`, res.status);
    return res.json();
  }

  async getCollectProfile(code: string): Promise<CollectProfileResponse> {
    const res = await fetch(
      `${getApiUrl()}/api/public/collect/${code}/profile`,
      { method: 'GET', headers: { 'Content-Type': 'application/json' }, credentials: 'include' },
    );
    if (!res.ok) {
      throw new ApiError(`getCollectProfile failed: ${res.status}`, res.status);
    }
    return res.json();
  }

  async setCollectProfile(
    code: string,
    data: { nickname?: string },
    reverify?: () => Promise<void>,
  ): Promise<CollectProfileResponse> {
    const doFetch = () =>
      fetch(`${getApiUrl()}/api/public/collect/${code}/profile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(data),
      });
    if (reverify) {
      return withHumanRetry<CollectProfileResponse>(doFetch, reverify);
    }
    const res = await doFetch();
    if (res.status === 409) {
      const body = await res.json().catch(() => ({})) as { detail?: { claimed?: boolean } };
      throw new NicknameConflictError(body.detail?.claimed ?? false);
    }
    if (!res.ok) throw new ApiError(`setCollectProfile failed: ${res.status}`, res.status);
    return res.json();
  }

  async getCollectMyPicks(code: string): Promise<CollectMyPicksResponse> {
    const res = await fetch(`${getApiUrl()}/api/public/collect/${code}/profile/me`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
    });
    if (!res.ok) throw new ApiError(`getCollectMyPicks failed: ${res.status}`, res.status);
    return res.json();
  }

  async submitCollectRequest(
    code: string,
    data: {
      song_title: string;
      artist: string;
      source: 'spotify' | 'beatport' | 'tidal' | 'manual';
      source_url?: string;
      artwork_url?: string;
      note?: string;
      nickname?: string;
    },
    reverify?: () => Promise<void>,
  ): Promise<{ id: number; is_duplicate: boolean }> {
    const doFetch = () =>
      fetch(`${getApiUrl()}/api/public/collect/${code}/requests`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(data),
      });
    if (reverify) {
      return withHumanRetry<{ id: number; is_duplicate: boolean }>(doFetch, reverify);
    }
    const res = await doFetch();
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(body.detail ?? `Submit failed: ${res.status}`, res.status);
    }
    return res.json();
  }

  async voteCollectRequest(
    code: string,
    requestId: number,
    reverify?: () => Promise<void>,
  ): Promise<void> {
    const doFetch = () =>
      fetch(`${getApiUrl()}/api/public/collect/${code}/vote`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ request_id: requestId }),
      });
    if (reverify) {
      return withHumanRetry<void>(doFetch, reverify);
    }
    const res = await doFetch();
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(body.detail ?? `Vote failed: ${res.status}`, res.status);
    }
  }

  // Note: returns `key` (not `musical_key`) to match EnrichPreviewResult schema —
  // callers merging results into SearchResult use `.key`; leaderboard fields use `.musical_key`.
  //
  // Sends credentials because the endpoint is now gated by require_email_verified
  // (post-2026-05-20 collection hardening). On any failure (403, network, etc.),
  // we fall back to the unenriched items so search UX degrades gracefully.
  async enrichPreview(
    code: string,
    items: Array<{ title: string; artist: string; source_url?: string }>,
  ): Promise<Array<{ title: string; artist: string; bpm?: number | null; key?: string | null; genre?: string | null }>> {
    try {
      const res = await fetch(
        `${getApiUrl()}/api/public/collect/${code}/enrich-preview`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ items }),
        },
      );
      if (!res.ok) return items.map((i) => ({ title: i.title, artist: i.artist }));
      const data = await res.json();
      return data.results ?? [];
    } catch {
      return items.map((i) => ({ title: i.title, artist: i.artist }));
    }
  }

  async getCollectPreview(
    code: string,
    requestId: number,
    reverify?: () => Promise<void>,
  ): Promise<CollectPreviewResponse> {
    const doFetch = () =>
      fetch(`${getApiUrl()}/api/public/collect/${code}/requests/${requestId}/preview`, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
      });
    if (reverify) {
      return withHumanRetry<CollectPreviewResponse>(doFetch, reverify);
    }
    const res = await doFetch();
    if (!res.ok) throw new ApiError(`getCollectPreview failed: ${res.status}`, res.status);
    return res.json();
  }

  // ========== Pre-Event Collection (DJ-authenticated) ==========

  async getCollectionSettings(code: string): Promise<CollectionSettingsResponse> {
    return this.fetch(`/api/events/${code}/collection`);
  }

  async patchCollectionSettings(
    code: string,
    data: {
      collection_opens_at?: string | null;
      live_starts_at?: string | null;
      submission_cap_per_guest?: number;
      collection_phase_override?: 'force_collection' | 'force_live' | null;
      tidal_sync_enabled?: boolean;
      tidal_collection_bidirectional?: boolean;
    },
  ): Promise<CollectionSettingsResponse> {
    return this.fetch(`/api/events/${code}/collection`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async syncCollectionToTidal(code: string): Promise<CollectionSyncResponse> {
    return this.fetch(`/api/events/${code}/collection/sync-tidal`, { method: 'POST' });
  }

  async getPendingReview(code: string): Promise<PendingReviewResponse> {
    return this.fetch(`/api/events/${code}/pending-review`);
  }

  async bulkReview(
    code: string,
    data: {
      action:
        | 'accept_top_n'
        | 'accept_threshold'
        | 'accept_ids'
        | 'reject_ids'
        | 'reject_remaining';
      n?: number;
      min_votes?: number;
      request_ids?: number[];
    },
  ): Promise<BulkReviewResponse> {
    return this.fetch(`/api/events/${code}/bulk-review`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // ========== Guest Email Verification ==========

  async requestVerificationCode(
    email: string,
    turnstileToken: string,
  ): Promise<{ sent: boolean }> {
    const resp = await fetch(`${getApiUrl()}/api/public/guest/verify/request`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ email, turnstile_token: turnstileToken }),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new ApiError((data as { detail?: string }).detail || 'Failed to send code', resp.status);
    }
    return resp.json();
  }

  async confirmVerificationCode(
    email: string,
    code: string
  ): Promise<{ verified: boolean; guest_id: number; merged: boolean }> {
    const resp = await fetch(`${getApiUrl()}/api/public/guest/verify/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ email, code }),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new ApiError((data as { detail?: string }).detail || 'Verification failed', resp.status);
    }
    return resp.json();
  }

  // ========== Bridge Commands ==========

  async sendBridgeCommand(eventCode: string, command: string): Promise<BridgeCommandResponse> {
    return this.fetch<BridgeCommandResponse>(`/api/bridge/commands/${eventCode}`, {
      method: 'POST',
      body: JSON.stringify({ command_type: command }),
    });
  }

  // ========== Activity Log ==========

  async getActivityLog(eventCode?: string, limit: number = 50): Promise<ActivityLogEntry[]> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (eventCode) params.set('event_code', eventCode);
    return this.fetch(`/api/events/activity?${params}`);
  }
}

export const api = new ApiClient();
export const apiClient = api;
