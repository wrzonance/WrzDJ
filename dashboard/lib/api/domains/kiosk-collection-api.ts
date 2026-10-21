import type { ApiTransport } from '../transport';
import type { CollectEventPreview, CollectLeaderboardResponse, CollectProfileResponse, CollectMyPicksResponse, CollectPreviewResponse, CollectionSettingsResponse, CollectionSyncResponse, BulkReviewResponse } from '../contracts';
import {
  getApiUrl,
  NicknameConflictError,
  responseError,
  withHumanRetry,
} from '../shared';
import type { ActivityLogEntry, BridgeCommandResponse, KioskInfo, KioskPairResponse, KioskPairStatusResponse, KioskSessionResponse, PendingReviewResponse } from '../types';
import { appendRequestListQueryParams, type RequestListQueryOptions } from './request-query';

interface EnrichPreviewItem {
  title: string;
  artist: string;
  source_url?: string;
}

interface EnrichPreviewTrack {
  title: string;
  artist: string;
  bpm: number | null;
  key: string | null;
  genre: string | null;
}

const PREVIEW_ENRICHMENT_ERROR = 'Preview enrichment is temporarily unavailable. Please try again.';

class PreviewEnrichmentError extends Error {
  readonly cause?: unknown;

  constructor(cause: unknown) {
    super(PREVIEW_ENRICHMENT_ERROR);
    this.name = 'PreviewEnrichmentError';
    this.cause = cause;
  }
}

function parseEnrichPreviewResults(data: unknown, items: EnrichPreviewItem[]): EnrichPreviewTrack[] {
  if (!data || typeof data !== 'object' || !Array.isArray((data as { results?: unknown }).results)) {
    throw new TypeError('Missing enrichment results');
  }
  const results = (data as { results: unknown[] }).results;
  if (results.length !== items.length) throw new TypeError('Unexpected enrichment result count');

  return results.map((value, index) => {
    if (!value || typeof value !== 'object') throw new TypeError('Invalid enrichment result');
    const result = value as Record<string, unknown>;
    const item = items[index];
    if (result.title !== item.title || result.artist !== item.artist) {
      throw new TypeError('Enrichment result identity mismatch');
    }
    const { bpm, key, genre } = result;
    if (bpm != null && (typeof bpm !== 'number' || !Number.isFinite(bpm))) {
      throw new TypeError('Invalid enrichment BPM');
    }
    if (key != null && typeof key !== 'string') throw new TypeError('Invalid enrichment key');
    if (genre != null && typeof genre !== 'string') throw new TypeError('Invalid enrichment genre');

    return {
      title: item.title,
      artist: item.artist,
      bpm: bpm ?? null,
      key: key ?? null,
      genre: genre ?? null,
    };
  });
}

export class KioskCollectionApi {
  constructor(public readonly transport: ApiTransport) {}

  async getKioskPairChallenge(): Promise<{ nonce: string; expires_in: number }> {
    return this.transport.publicFetch(`${getApiUrl()}/api/public/kiosk/pair-challenge`, {
      credentials: 'include',
    });
  }

  async createKioskPairing(nonce: string): Promise<KioskPairResponse> {
    return this.transport.publicFetch(`${getApiUrl()}/api/public/kiosk/pair`, {
      method: 'POST',
      headers: { 'X-Pair-Nonce': nonce },
      credentials: 'include',
    });
  }

  async getKioskPairStatus(pairCode: string): Promise<KioskPairStatusResponse> {
    return this.transport.publicFetch(`${getApiUrl()}/api/public/kiosk/pair/${pairCode}/status`);
  }

  async getKioskAssignment(sessionToken: string): Promise<KioskSessionResponse> {
    return this.transport.publicFetch(`${getApiUrl()}/api/public/kiosk/session/assignment`, {
      headers: { 'X-Kiosk-Session': sessionToken },
    });
  }

  async completeKioskPairing(
    pairCode: string,
    eventCode: string
  ): Promise<KioskInfo> {
    return this.transport.fetch(`/api/kiosk/pair/${pairCode}/complete`, {
      method: 'POST',
      body: JSON.stringify({ event_code: eventCode }),
    });
  }

  async getMyKiosks(): Promise<KioskInfo[]> {
    return this.transport.fetch('/api/kiosk/mine');
  }

  async assignKiosk(kioskId: number, eventCode: string): Promise<KioskInfo> {
    return this.transport.fetch(`/api/kiosk/${kioskId}/assign`, {
      method: 'PATCH',
      body: JSON.stringify({ event_code: eventCode }),
    });
  }

  async renameKiosk(kioskId: number, name: string | null): Promise<KioskInfo> {
    return this.transport.fetch(`/api/kiosk/${kioskId}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    });
  }

  async deleteKiosk(kioskId: number): Promise<void> {
    await this.transport.rawFetch(`/api/kiosk/${kioskId}`, { method: 'DELETE' });
  }

  // ========== Pre-Event Collection (Public) ==========

  async getCollectEvent(code: string): Promise<CollectEventPreview> {
    return this.transport.publicFetch(`${getApiUrl()}/api/public/collect/${code}`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });
  }

  async getCollectLeaderboard(
    code: string,
    tab: 'trending' | 'all' = 'trending',
    options?: { limit?: number; offset?: number },
  ): Promise<CollectLeaderboardResponse> {
    const qs = new URLSearchParams({ tab });
    if (options?.limit != null) qs.set('limit', String(options.limit));
    if (options?.offset != null) qs.set('offset', String(options.offset));
    return this.transport.publicFetch(
      `${getApiUrl()}/api/public/collect/${code}/leaderboard?${qs}`,
      { method: 'GET', headers: { 'Content-Type': 'application/json' } },
    );
  }

  async getJoinConfig(code: string): Promise<{ frictionless_join: boolean }> {
    return this.transport.publicFetch(`${getApiUrl()}/api/public/collect/${code}/join-config`);
  }

  async ensureGuestName(
    code: string,
    options: { nickname?: string; reverify?: () => Promise<void> } = {},
  ): Promise<{ nickname: string; auto_generated: boolean }> {
    const { nickname, reverify } = options;
    const doFetch = () =>
      fetch(`${getApiUrl()}/api/public/collect/${code}/guest/ensure-name`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(nickname ? { nickname } : {}),
      });
    return withHumanRetry(doFetch, reverify ?? (async () => {}));
  }

  async updateMyPreferences(prefs: { frictionless_join_default: boolean }): Promise<void> {
    await this.transport.fetch('/api/auth/me/preferences', {
      method: 'PATCH',
      body: JSON.stringify(prefs),
    });
  }

  async getCollectProfile(code: string): Promise<CollectProfileResponse> {
    return this.transport.publicFetch(
      `${getApiUrl()}/api/public/collect/${code}/profile`,
      { method: 'GET', headers: { 'Content-Type': 'application/json' }, credentials: 'include' },
    );
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
    if (!res.ok) {
      const error = await responseError(res, 'Request failed');
      if (res.status === 409 && error.code === 'nickname_taken') {
        const detail = error.detail;
        const claimed = detail && typeof detail === 'object' && 'claimed' in detail
          ? detail.claimed === true
          : false;
        throw new NicknameConflictError(claimed);
      }
      throw error;
    }
    return res.json();
  }

  async getCollectMyPicks(code: string): Promise<CollectMyPicksResponse> {
    return this.transport.publicFetch(`${getApiUrl()}/api/public/collect/${code}/profile/me`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
    });
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
      isrc?: string;
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
      throw await responseError(res, `Submit failed: ${res.status}`);
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
      await withHumanRetry<void>(doFetch, reverify);
      return;
    }
    const res = await doFetch();
    if (!res.ok) {
      throw await responseError(res, `Vote failed: ${res.status}`);
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
    items: EnrichPreviewItem[],
  ): Promise<EnrichPreviewTrack[]> {
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
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return parseEnrichPreviewResults(await res.json(), items);
    } catch (cause) {
      throw new PreviewEnrichmentError(cause);
    }
  }

  async getCollectPreview(
    code: string,
    requestId: number,
    reverify?: () => Promise<void>,
  ): Promise<CollectPreviewResponse> {
    const url = `${getApiUrl()}/api/public/collect/${code}/requests/${requestId}/preview`;
    const options: RequestInit = {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
    };
    if (!reverify) {
      return this.transport.publicFetch(url, options);
    }
    const doFetch = () =>
      fetch(url, options);
    return withHumanRetry<CollectPreviewResponse>(doFetch, reverify);
  }

  // ========== Pre-Event Collection (DJ-authenticated) ==========

  async getCollectionSettings(code: string): Promise<CollectionSettingsResponse> {
    return this.transport.fetch(`/api/events/${code}/collection`);
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
    return this.transport.fetch(`/api/events/${code}/collection`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async syncCollectionToTidal(code: string): Promise<CollectionSyncResponse> {
    return this.transport.fetch(`/api/events/${code}/collection/sync-tidal`, { method: 'POST' });
  }

  /**
   * Pre-event pending-review list (issue #478). Returns the paginated envelope
   * (`requests`/`total`/`limit`/`offset`/`sort`/`direction`). Omitting `sort`
   * yields the default vote-ranked "Review order" (votes desc, age asc); pass a
   * `RequestSort` value to override. `limit` is forwarded unchanged; the backend returns HTTP 422
   * when it exceeds {@link PUBLIC_PAGE_MAX}.
   */
  async getPendingReview(
    code: string,
    options?: RequestListQueryOptions,
  ): Promise<PendingReviewResponse> {
    const params = new URLSearchParams();
    const qs = appendRequestListQueryParams(params, options).toString();
    return this.transport.fetch(`/api/events/${code}/pending-review${qs ? `?${qs}` : ''}`);
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
    return this.transport.fetch(`/api/events/${code}/bulk-review`, {
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
      throw await responseError(resp, 'Failed to send code');
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
      throw await responseError(resp, 'Verification failed');
    }
    return resp.json();
  }

  // ========== Bridge Commands ==========

  async sendBridgeCommand(eventCode: string, command: string): Promise<BridgeCommandResponse> {
    return this.transport.fetch<BridgeCommandResponse>(`/api/bridge/commands/${eventCode}`, {
      method: 'POST',
      body: JSON.stringify({ command_type: command }),
    });
  }

  // ========== Activity Log ==========

  async getActivityLog(eventCode?: string, limit: number = 50): Promise<ActivityLogEntry[]> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (eventCode) params.set('event_code', eventCode);
    return this.transport.fetch(`/api/events/activity?${params}`);
  }}
