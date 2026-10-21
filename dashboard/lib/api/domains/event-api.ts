import {
  ApiError,
  CSRF_HEADER_NAME,
  CSRF_HEADER_VALUE,
  getApiUrl,
  responseJson,
  withHumanRetry,
} from '../shared';
import type { ArchivedEvent, DisplaySettingsResponse, PublicBridgeStatus, GuestRequestListResponse, HasRequestedResponse, KioskDisplay, MyRequestsResponse, NowPlayingInfo, PlayHistoryResponse, PublicEvent, SearchResult, SongRequest, RequestListResponse, RequestStatus, VoteResponse } from '../types';
import type { ApiTransport } from '../transport';
import { appendRequestListQueryParams, type RequestListQueryOptions } from './request-query';

export interface SubmitRequestInput {
  eventCode: string;
  artist: string;
  title: string;
  note?: string;
  sourceUrl?: string;
  artworkUrl?: string;
  rawSearchQuery?: string;
  metadata?: {
    source?: string;
    genre?: string;
    bpm?: number;
    musical_key?: string;
    isrc?: string;
  };
  nickname?: string;
  reverify?: () => Promise<void>;
}

export class EventApi {
  constructor(public readonly transport: ApiTransport) {}

  async bulkDeleteEvents(codes: string[]): Promise<{ status: string; count: number }> {
    return this.transport.fetch('/api/events/bulk-delete', {
      method: 'POST',
      body: JSON.stringify({ codes }),
    });
  }

  /**
   * DJ request list (issue #478). Returns the paginated envelope
   * (`requests`/`total`/`limit`/`offset`/`sort`/`direction`) so the dashboard
   * never infers the row count from a page length.
   *
   * `limit` is forwarded unchanged. The backend rejects values above its
   * maximum page size with HTTP 422.
   */
  async getRequests(
    code: string,
    options?: RequestListQueryOptions & {
      status?: string;
    },
  ): Promise<RequestListResponse> {
    const params = new URLSearchParams();
    if (options?.status) params.set('status', options.status);
    const qs = appendRequestListQueryParams(params, options).toString();
    return this.transport.fetch(`/api/events/${code}/requests${qs ? `?${qs}` : ''}`);
  }

  async acceptAllRequests(code: string): Promise<{ status: string; accepted_count: number }> {
    return this.transport.fetch(`/api/events/${code}/requests/accept-all`, {
      method: 'POST',
    });
  }

  async rejectAllRequests(code: string): Promise<{ status: string; count: number }> {
    return this.transport.fetch(`/api/events/${code}/requests/reject-all`, {
      method: 'POST',
    });
  }

  async bulkDeleteRequests(code: string, status?: string): Promise<{ status: string; count: number }> {
    const params = status ? `?status=${status}` : '';
    return this.transport.fetch(`/api/events/${code}/requests/bulk${params}`, {
      method: 'DELETE',
    });
  }

  async updateRequestStatus(requestId: number, status: RequestStatus): Promise<SongRequest> {
    return this.transport.fetch(`/api/requests/${requestId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
  }

  async deleteRequest(requestId: number): Promise<void> {
    await this.transport.rawFetch(`/api/requests/${requestId}`, { method: 'DELETE' });
  }

  async refreshRequestMetadata(requestId: number): Promise<SongRequest> {
    return this.transport.fetch(`/api/requests/${requestId}/refresh-metadata`, {
      method: 'POST',
    });
  }

  async enrichAllRequests(code: string): Promise<{ queued: number; remaining: number }> {
    return this.transport.fetch(`/api/events/${encodeURIComponent(code)}/enrich-all`, {
      method: 'POST',
    });
  }

  async submitRequest(input: SubmitRequestInput): Promise<SongRequest> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      [CSRF_HEADER_NAME]: CSRF_HEADER_VALUE,
    };
    if (this.transport.kioskSession) headers['X-Kiosk-Session'] = this.transport.kioskSession;
    const doFetch = () =>
      fetch(`${getApiUrl()}/api/events/${input.eventCode}/requests`, {
        method: 'POST',
        headers,
        credentials: 'include',
        body: JSON.stringify({
          artist: input.artist,
          title: input.title,
          note: input.note,
          nickname: input.nickname,
          source: input.metadata?.source ?? 'spotify',
          source_url: input.sourceUrl,
          artwork_url: input.artworkUrl,
          raw_search_query: input.rawSearchQuery,
          genre: input.metadata?.genre,
          bpm: input.metadata?.bpm,
          musical_key: input.metadata?.musical_key,
          isrc: input.metadata?.isrc,
        }),
      });
    if (input.reverify) {
      return withHumanRetry<SongRequest>(doFetch, input.reverify);
    }
    const res = await doFetch();
    if (!res.ok) {
      if (res.status === 401 && this.transport.onUnauthorized) {
        this.transport.onUnauthorized();
      }
      return responseJson<SongRequest>(res, 'Submit failed');
    }
    return res.json();
  }

  async search(query: string): Promise<SearchResult[]> {
    return this.transport.fetch(`/api/search?q=${encodeURIComponent(query)}`);
  }

  async eventSearch(
    code: string,
    query: string,
    reverify?: () => Promise<void>,
  ): Promise<SearchResult[]> {
    const doFetch = () => {
      // The dashboard authenticates through its HttpOnly cookie. Guests fall
      // through to the cookie-based gate + reverify retry.
      const headers: Record<string, string> = { [CSRF_HEADER_NAME]: CSRF_HEADER_VALUE };
      if (this.transport.kioskSession) headers['X-Kiosk-Session'] = this.transport.kioskSession;
      return fetch(`${getApiUrl()}/api/events/${code}/search?q=${encodeURIComponent(query)}`, {
        credentials: 'include',
        headers,
      });
    };
    if (reverify) {
      return withHumanRetry<SearchResult[]>(doFetch, reverify);
    }
    const res = await doFetch();
    if (!res.ok) {
      return responseJson<SearchResult[]>(res);
    }
    return res.json();
  }

  async voteRequest(requestId: number): Promise<VoteResponse> {
    return this.transport.fetch(`/api/requests/${requestId}/vote`, { method: 'POST' });
  }

  async unvoteRequest(requestId: number): Promise<VoteResponse> {
    return this.transport.fetch(`/api/requests/${requestId}/vote`, { method: 'DELETE' });
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
      return responseJson<VoteResponse>(res, 'Vote failed');
    }
    return res.json();
  }

  async publicUnvoteRequest(
    requestId: number,
    reverify?: () => Promise<void>,
  ): Promise<VoteResponse> {
    const doFetch = () =>
      fetch(`${getApiUrl()}/api/requests/${requestId}/vote`, {
        method: 'DELETE',
        credentials: 'include',
      });
    if (reverify) {
      return withHumanRetry<VoteResponse>(doFetch, reverify);
    }
    const res = await doFetch();
    if (!res.ok) {
      return responseJson<VoteResponse>(res, 'Vote removal failed');
    }
    return res.json();
  }

  async getArchivedEvents(): Promise<ArchivedEvent[]> {
    return this.transport.fetch('/api/events/archived');
  }

  async exportEventCsv(code: string): Promise<boolean | null> {
    return this.transport.downloadCsvBlob(
      `${getApiUrl()}/api/events/${code}/export/csv`,
      `${code}.csv`
    );
  }

  async exportPlayHistoryCsv(code: string): Promise<boolean | null> {
    return this.transport.downloadCsvBlob(
      `${getApiUrl()}/api/events/${code}/export/play-history/csv`,
      `${code}_play_history.csv`
    );
  }

  async checkHasRequested(code: string): Promise<HasRequestedResponse> {
    const res = await fetch(`${getApiUrl()}/api/public/events/${code}/has-requested`, {
      credentials: 'include',
    });
    if (!res.ok) {
      return responseJson<HasRequestedResponse>(res, `checkHasRequested failed: ${res.status}`);
    }
    return res.json();
  }

  async getMyRequests(code: string): Promise<MyRequestsResponse> {
    const res = await fetch(`${getApiUrl()}/api/public/events/${code}/my-requests`, {
      credentials: 'include',
    });
    if (!res.ok) {
      return responseJson<MyRequestsResponse>(res, `getMyRequests failed: ${res.status}`);
    }
    return res.json();
  }

  async getPublicRequests(
    code: string,
    options?: { limit?: number; offset?: number },
  ): Promise<GuestRequestListResponse> {
    const qs = new URLSearchParams();
    if (options?.limit != null) qs.set('limit', String(options.limit));
    if (options?.offset != null) qs.set('offset', String(options.offset));
    const suffix = qs.toString() ? `?${qs}` : '';
    return this.transport.publicFetch(`${getApiUrl()}/api/public/events/${code}/requests${suffix}`);
  }

  async getPublicEvent(code: string): Promise<PublicEvent> {
    return this.transport.publicFetch(`${getApiUrl()}/api/public/events/${code}`);
  }

  async getKioskDisplay(
    code: string,
    options?: { limit?: number; offset?: number },
  ): Promise<KioskDisplay> {
    const qs = new URLSearchParams();
    if (options?.limit !== undefined) qs.set('limit', String(options.limit));
    if (options?.offset !== undefined) qs.set('offset', String(options.offset));
    const suffix = qs.toString() ? `?${qs}` : '';
    return this.transport.publicFetch(`${getApiUrl()}/api/public/events/${code}/display${suffix}`);
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
      throw new ApiError(`getNowPlaying failed: ${response.status}`, response.status);
    }
    const data = await response.json();
    return data || null;
  }

  /**
   * Get bridge connection status (independent of track data).
   */
  async getBridgeStatus(code: string): Promise<PublicBridgeStatus> {
    return this.transport.publicFetch(`${getApiUrl()}/api/public/e/${code}/bridge-status`);
  }

  /**
   * Get play history for an event.
   */
  async getPlayHistory(
    code: string,
    options: { limit?: number; offset?: number } = {},
  ): Promise<PlayHistoryResponse> {
    const limit = options.limit ?? 100;
    const offset = options.offset ?? 0;
    return this.transport.publicFetch(
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
    return this.transport.fetch(`/api/events/${code}/display-settings`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  }

  /**
   * Update only the auto-hide timeout without affecting visibility state.
   */
  async setAutoHideMinutes(code: string, minutes: number): Promise<DisplaySettingsResponse> {
    return this.transport.fetch(`/api/events/${code}/display-settings`, {
      method: 'PATCH',
      body: JSON.stringify({ now_playing_auto_hide_minutes: minutes }),
    });
  }

  /**
   * Get current display settings for an event.
   */
  async getDisplaySettings(code: string): Promise<DisplaySettingsResponse> {
    return this.transport.fetch(`/api/events/${code}/display-settings`);
  }

  /**
   * Open or close song requests for an event.
   */
  async setRequestsOpen(code: string, open: boolean): Promise<DisplaySettingsResponse> {
    return this.transport.fetch(`/api/events/${code}/display-settings`, {
      method: 'PATCH',
      body: JSON.stringify({ requests_open: open }),
    });
  }

  /**
   * Toggle kiosk display-only mode.
   */
  async setKioskDisplayOnly(code: string, displayOnly: boolean): Promise<DisplaySettingsResponse> {
    return this.transport.fetch(`/api/events/${code}/display-settings`, {
      method: 'PATCH',
      body: JSON.stringify({ kiosk_display_only: displayOnly }),
    });
  }

  // ========== Tidal Integration ==========


}
