import { EventApi } from './domains/event-api';
import { AccountApi } from './domains/account-api';
import { SetbuilderApi } from './domains/setbuilder-api';
import { IntegrationsApi } from './domains/integrations-api';
import { AdminApi } from './domains/admin-api';
import { KioskCollectionApi } from './domains/kiosk-collection-api';
import {
  ApiError, CSRF_HEADER_NAME, CSRF_HEADER_VALUE, apiErrorFromBody, getApiUrl, responseJson,
} from './shared';
export {
  ApiError, CSRF_HEADER_NAME, CSRF_HEADER_VALUE, EmailVerificationRequiredError,
  getApiUrl, HumanVerificationRequiredError, NicknameConflictError, withHumanRetry,
} from './shared';
export {
  PUBLIC_PAGE_MAX,
  type AdminLlmAuditFilters,
  type BulkReviewResponse,
  type CollectEventPreview,
  type CollectLeaderboardResponse,
  type CollectLeaderboardRow,
  type CollectMyPicksItem,
  type CollectMyPicksResponse,
  type CollectPreviewResponse,
  type CollectProfileResponse,
  type CollectionSettingsResponse,
  type CollectionSyncResponse,
  type LlmStreamChunk,
} from './contracts';
export type {
  ArchivedEvent,
  DisplaySettingsResponse,
  GuestRequestListResponse,
  HasRequestedResponse,
  KioskDisplay,
  MyRequestsResponse,
  NowPlayingInfo,
  PlayHistoryResponse,
  PublicBridgeStatus,
  PublicEvent,
  RequestListResponse,
  SearchResult,
  SongRequest,
  VoteResponse,
} from './types';

export type {
  ActivityLogEntry,
  AdminEvent,
  AdminGuest,
  AdminGuestEvent,
  AdminGuestFilter,
  AdminGuestProfileUpdate,
  AdminGuestUpdate,
  AdminUser,
  AIModelInfo,
  AIModelsResponse,
  AISettings,
  AISettingsUpdate,
  LlmAdminAudit,
  LlmAdminConnector,
  LlmAdminPolicy,
  LlmAdminPolicyPatch,
  LlmAdminUsage,
  LlmAuditRow,
  LlmConnector,
  LlmConnectorCreate,
  LlmConnectorCredentialsRotate,
  LlmConnectorPatch,
  LlmConnectorStatus,
  LlmConnectorTestResult,
  LlmConnectorType,
  LlmDjPolicy,
  LlmDjStatus,
  LlmDjStatusRow,
  LlmFeatureKey,
  LlmFeaturePreference,
  LlmFeaturePreferences,
  LlmFeaturePreferenceSet,
  LlmUsageRow,
  AgentChatHistory,
  AgentChatMessage,
  AgentChatIn,
  AgentChatOut,
  BeatportEventSettings,
  BeatportSearchResult,
  BeatportStatus,
  AppleMusicStatus,
  AppleMusicDeveloperToken,
  BridgeCommandResponse,
  BridgeEnrichedStatus,
  BuildSetResponse,
  CapabilityStatus,
  Event,
  EventMusicProfile,
  GuestNowPlaying,
  GuestRequestInfo,
  IntegrationCheckResponse,
  IntegrationHealthResponse,
  IntegrationServiceStatus,
  IntegrationToggleResponse,
  KioskInfo,
  KioskPairResponse,
  KioskPairStatusResponse,
  KioskSessionResponse,
  LLMQueryInfo,
  LLMRecommendationResponse,
  MyRequestInfo,
  PaginatedResponse,
  Pairing,
  PairingCreate,
  PairingUpdate,
  PairingsState,
  PlaybackReport,
  ApplyPairingFeedback,
  PlayHistoryItem,
  PublicRequestInfo,
  RecommendationResponse,
  RecommendedTrack,
  ServiceCapabilities,
  SetCritique,
  SetDocumentSnapshot,
  SetDetail,
  SetSummary,
  SetTemplate,
  SetTemplateGalleryResponse,
  SharedCurvePointView,
  SharedSetView,
  SharedSlotView,
  ShareTokenOut,
  PendingReviewResponse,
  PendingReviewRow,
  RequestSort,
  SortDirection,
  SyncResultEntry,
  SystemSettings,
  SystemStats,
  TasteProfile,
  TidalEventSettings,
  TidalSearchResult,
  TidalSyncResult,
  TidalStatus,
  TransportCommandIn,
  TransportCommandOut,
  TransportStatusOut,
  ExportTarget,
  ExportFileFormat,
  ExportPreflight,
  ExportTidalResult,
  ExportSpotifyResult,
  ExportAppleMusicResult,
  ExportAppleMusicRecoveryRequest,
  ExportAppleMusicRecoveryResult,
  UnresolvedTrack,
} from './types';

class ApiClient {
  kioskSession: string | null = null;
  onUnauthorized: (() => void) | null = null;

  /**
   * Register the kiosk's session token. A paired kiosk is a trusted physical
   * device with no JWT and no human-verification cookie, so it sends this token
   * as X-Kiosk-Session on the public event search/submit endpoints to bypass
   * the guest human-verification gate (issue #514). Set once on the kiosk
   * display page; null on every other client.
   */
  setKioskSession(token: string | null) {
    this.kioskSession = token;
  }

  /**
   * Register a callback for 401 responses on authenticated endpoints.
   * Used by AuthProvider to auto-logout on token expiration.
   */
  setUnauthorizedHandler(handler: (() => void) | null) {
    this.onUnauthorized = handler;
  }

  async fetch<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers = new Headers({
      'Content-Type': 'application/json',
    });

    if (options.headers) {
      new Headers(options.headers).forEach((value, key) => {
        headers.set(key, value);
      });
    }

    headers.set(CSRF_HEADER_NAME, CSRF_HEADER_VALUE);

    const response = await fetch(`${getApiUrl()}${path}`, {
      credentials: 'include',
      ...options,
      headers,
    });

    if (!response.ok) {
      if (response.status === 401 && this.onUnauthorized) {
        this.onUnauthorized();
      }
      const error = await response.json().catch(() => ({ detail: 'Request failed' }));
      throw apiErrorFromBody(error, response.status);
    }

    if (response.status === 204) {
      throw new ApiError('Expected a JSON response but received 204 No Content', 204);
    }

    return response.json();
  }

  /**
   * Make an authenticated raw fetch (no JSON content-type, no JSON parsing).
   * Returns the raw Response. Handles 401 → onUnauthorized.
   */
  async rawFetch(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    headers.set(CSRF_HEADER_NAME, CSRF_HEADER_VALUE);

    const url = path.startsWith('http') ? path : `${getApiUrl()}${path}`;
    const response = await fetch(url, { credentials: 'include', ...init, headers });

    if (!response.ok) {
      if (response.status === 401 && this.onUnauthorized) {
        this.onUnauthorized();
      }
      const error = await response.json().catch(() => ({ detail: 'Request failed' }));
      throw apiErrorFromBody(error, response.status);
    }

    return response;
  }

  /**
   * Fetch a public (no-auth) endpoint and parse JSON response.
   * Throws ApiError on non-OK responses.
   */
  async publicFetch<T>(url: string, options?: RequestInit): Promise<T> {
    const response = await fetch(url, options);
    return responseJson<T>(response);
  }

  /**
   * Download a CSV blob from an authenticated endpoint and trigger browser download.
   * Parses filename from Content-Disposition header, falling back to the provided default.
   */
  async downloadCsvBlob(url: string, defaultFilename: string): Promise<boolean | null> {
    const response = await this.rawFetch(url);
    const truncationHeader = response.headers.get('X-Export-Truncated');
    const truncated = truncationHeader === 'true'
      ? true
      : truncationHeader === 'false'
        ? false
        : null;
    const blob = await response.blob();
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    const contentDisposition = response.headers.get('Content-Disposition');
    const filenameMatch = contentDisposition?.match(/filename=([^;]+)/);
    a.download = filenameMatch ? filenameMatch[1].replace(/"/g, '') : defaultFilename;
    a.click();
    URL.revokeObjectURL(blobUrl);
    return truncated;
  }


}

const apiTransport = new ApiClient();
const domains = [
  new EventApi(apiTransport),
  new AccountApi(apiTransport),
  new SetbuilderApi(apiTransport),
  new IntegrationsApi(apiTransport),
  new AdminApi(apiTransport),
  new KioskCollectionApi(apiTransport),
];

// Compose stable, bound methods onto the existing transport client. Keeping these
// as own properties preserves the historical `api.method` surface for consumers
// and lets callers/test boundaries replace a method without proxy dispatch.
const composedMethods: Record<string, (...args: never[]) => unknown> = {};
for (const domain of domains) {
  const prototype = Object.getPrototypeOf(domain) as object;
  for (const name of Object.getOwnPropertyNames(prototype)) {
    if (name === 'constructor' || name in apiTransport || name in composedMethods) continue;
    const method = Reflect.get(domain, name);
    if (typeof method === 'function') composedMethods[name] = method.bind(domain);
  }
}
Object.assign(apiTransport, composedMethods);

export const api = apiTransport as ApiClient & EventApi & AccountApi & SetbuilderApi & IntegrationsApi & AdminApi & KioskCollectionApi;
