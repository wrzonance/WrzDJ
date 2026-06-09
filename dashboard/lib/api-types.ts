/**
 * Public API type surface for the dashboard.
 *
 * Most types are re-exported from `./api-types.generated.ts`, which is
 * auto-generated from the FastAPI OpenAPI spec via `npm run types:generate`.
 *
 * A handful of types are kept hand-crafted here because the corresponding
 * FastAPI endpoints don't declare `response_model=`, so they aren't part of
 * the OpenAPI components surface. These are flagged below.
 *
 * DO NOT edit `api-types.generated.ts` by hand. Instead, update the backend
 * schema + re-run `npm run types:generate`. CI validates zero drift.
 */

import type { components } from './api-types.generated';

type Schemas = components['schemas'];

// ---------------------------------------------------------------------------
// Auto-re-exports from the OpenAPI spec (aliased to historical TS names).
// ---------------------------------------------------------------------------

export type Event = Schemas['EventOut'];
export type PublicEvent = Schemas['PublicEventResponse'];
export type SongRequest = Schemas['RequestOut'];
export type PublicRequestInfo = Schemas['PublicRequestInfo'] & { requester_verified?: boolean };
export type GuestRequestInfo = Schemas['GuestRequestInfo'] & { requester_verified?: boolean };
export type GuestNowPlaying = Schemas['GuestNowPlaying'];
export type GuestRequestListResponse = Schemas['GuestRequestListResponse'];
export type MyRequestInfo = Schemas['MyRequestInfo'];
export type MyRequestsResponse = Schemas['MyRequestsResponse'];
export type HasRequestedResponse = Schemas['HasRequestedResponse'];
export type VoteResponse = Schemas['VoteResponse'];
export type KioskDisplay = Schemas['KioskDisplayResponse'];
export type DisplaySettingsResponse = Schemas['DisplaySettingsResponse'];
export type SearchResult = Schemas['SearchResult'];
export type NowPlayingInfo = Schemas['NowPlayingResponse'];
export type PlayHistoryItem = Schemas['PlayHistoryEntry'];
export type PlayHistoryResponse = Schemas['PlayHistoryResponse'];
export type TidalStatus = Schemas['TidalStatus'];
export type TidalSearchResult = Schemas['TidalSearchResult'];
export type TidalEventSettings = Schemas['TidalEventSettings'];
export type TidalSyncResult = Schemas['TidalSyncResult'];
export type BeatportStatus = Schemas['BeatportStatus'];
export type BeatportSearchResult = Schemas['BeatportSearchResult'];
export type BeatportEventSettings = Schemas['BeatportEventSettings'];
export type SystemStats = Schemas['SystemStats'];
export type AdminUser = Schemas['AdminUserOut'];
export type AdminEvent = Schemas['AdminEventOut'];
export type SystemSettings = Schemas['SystemSettingsOut'];
export type AIModelInfo = Schemas['AIModelInfo'];
export type AIModelsResponse = Schemas['AIModelsResponse'];
export type AISettings = Schemas['AISettingsOut'];
export type AISettingsUpdate = Schemas['AISettingsUpdate'];

// LLM gateway (issue #329)
export type LlmConnector = Schemas['ConnectorOut'];
export type LlmAdminConnector = Schemas['AdminConnectorOut'];
export type LlmConnectorCreate = Schemas['ConnectorCreate'];
export type LlmConnectorPatch = Schemas['ConnectorPatch'];
export type LlmConnectorCredentialsRotate = Schemas['ConnectorCredentialsRotate'];
export type LlmConnectorTestResult = Schemas['ConnectorTestResult'];
export type LlmAdminPolicy = Schemas['AdminPolicyOut'];
export type LlmAdminPolicyPatch = Schemas['AdminPolicyPatch'];
// Monthly token cap (issue #339)
export type LlmAdminConnectorCapPatch = Schemas['AdminConnectorCapPatch'];
export type LlmDjPolicy = Schemas['DjPolicyOut'];
export type LlmAdminUsage = Schemas['AdminUsageOut'];
export type LlmUsageRow = Schemas['UsageRow'];
// LLM audit trail (issue #341)
export type LlmAdminAudit = Schemas['AdminAuditOut'];
export type LlmAuditRow = Schemas['AuditEventRow'];
// Per-feature connector preference (issue #337)
export type LlmFeaturePreference = Schemas['FeaturePreferenceOut'];
export type LlmFeaturePreferences = Schemas['FeaturePreferencesListOut'];
export type LlmFeaturePreferenceSet = Schemas['FeaturePreferenceSet'];
export type LlmFeatureKey = Schemas['FeaturePreferenceOut']['feature'];
// Derive from schema so backend enum changes propagate to TS automatically.
export type LlmConnectorType = Schemas['ConnectorOut']['connector_type'];
export type LlmConnectorStatus = Schemas['ConnectorOut']['status'];
export type ActivityLogEntry = Schemas['ActivityLogEntry'];
export type CapabilityStatus = Schemas['CapabilityStatus'];
export type ServiceCapabilities = Schemas['ServiceCapabilities'];
export type IntegrationServiceStatus = Schemas['IntegrationServiceStatus'];
export type IntegrationHealthResponse = Schemas['IntegrationHealthResponse'];
export type IntegrationToggleResponse = Schemas['IntegrationToggleResponse'];
export type IntegrationCheckResponse = Schemas['IntegrationCheckResponse'];
export type KioskPairResponse = Schemas['KioskPairResponse'];
export type KioskPairStatusResponse = Schemas['KioskPairStatusResponse'];
export type KioskSessionResponse = Schemas['KioskSessionResponse'];
export type KioskInfo = Schemas['KioskOut'];
export type BridgeCommandResponse = Schemas['BridgeCommandResponse'];
export type RecommendedTrack = Schemas['RecommendedTrack'];
export type EventMusicProfile = Schemas['EventMusicProfile'];
export type RecommendationResponse = Schemas['RecommendationResponse'];

// ---------------------------------------------------------------------------
// Hand-crafted: endpoints without response_model=, or client-side synthetic
// shapes. When adding response_model to the backend, move the type here into
// the auto-re-export section above and delete the manual definition.
// ---------------------------------------------------------------------------

export interface ArchivedEvent extends Event {
  status: 'expired' | 'archived';
  request_count: number;
  archived_at: string | null;
}

export interface SyncResultEntry {
  service: string;
  status: 'matched' | 'added' | 'not_found' | 'error';
  track_id: string | null;
  track_title: string | null;
  track_artist: string | null;
  confidence: number | null;
  url: string | null;
  duration_seconds: number | null;
  playlist_id: string | null;
  error: string | null;
  error_code: string | null;
  extra: Record<string, unknown> | null;
}

export interface BridgeEnrichedStatus {
  circuit_breaker_state: string | null;
  buffer_size: number | null;
  plugin_id: string | null;
  deck_count: number | null;
  uptime_seconds: number | null;
}

export interface PublicBridgeStatus {
  connected: boolean;
  device_name: string | null;
  last_seen: string | null;
  circuit_breaker_state: string | null;
  buffer_size: number | null;
  plugin_id: string | null;
  deck_count: number | null;
  uptime_seconds: number | null;
}

export interface LLMQueryInfo {
  search_query: string;
  target_bpm: number | null;
  target_key: string | null;
  target_genre: string | null;
  reasoning: string;
}

export interface LLMRecommendationResponse {
  suggestions: RecommendedTrack[];
  profile: EventMusicProfile;
  services_used: string[];
  total_candidates_searched: number;
  llm_queries: LLMQueryInfo[];
  llm_available: boolean;
  llm_model: string;
}

export interface PlaylistInfo {
  id: string;
  name: string;
  num_tracks: number;
  description: string | null;
  cover_url: string | null;
  source: 'tidal' | 'beatport';
}

export interface PlaylistListResponse {
  playlists: PlaylistInfo[];
}

export interface SetSummary {
  id: number;
  name: string;
  event_id: number | null;
  status: 'draft' | 'locked' | 'exported';
  sharing_mode: 'private' | 'invite_only';
  /** Owner-only; non-null means a public read-only share link exists. */
  share_token: string | null;
  created_at: string;
  updated_at: string;
}

export interface SetDetail extends SetSummary {
  vibe_theme: string | null;
  target_duration_sec: number | null;
  bpm_floor: number | null;
  bpm_ceiling: number | null;
  key_strictness: number;
  tidal_playlist_id: string | null;
  exported_at: string | null;
}

// WrzDJSet energy curve editor (#389)
export type CurvePoint = Schemas['CurvePointModel'];
export type BuiltinCurveTemplate = Schemas['BuiltinTemplateOut'];
export type CurveTemplate = Schemas['CurveTemplateOut'];
export type CurveTemplatesResponse = Schemas['CurveTemplatesResponse'];
export type SetSlotOut = Schemas['SlotOut'];
export type SlotTargetOut = Schemas['SlotTargetOut'];
export type ApplyTemplateResponse = Schemas['ApplyTemplateResponse'];
export type VibeWindow = Schemas['VibeWindowModel'];
export type VibeWindowsResponse = Schemas['VibeWindowsResponse'];

// WrzDJSet pool (issue #388)
export type PoolSource = Schemas['PoolSourceOut'];
export type PoolTrack = Schemas['PoolTrackOut'];
export type PoolState = Schemas['PoolState'];
export type PoolImportResult = Schemas['PoolImportResult'];
export type PoolMutationResult = Schemas['PoolMutationResult'];
export type PoolUrlPreview = Schemas['PoolUrlPreview'];
export type PoolImportManualIn = Schemas['PoolImportManualIn'];
export type BuilderPlaylists = Schemas['BuilderPlaylistsOut'];

// WrzDJSet sharing + duplication (issue #398)
export interface ShareTokenOut {
  share_token: string;
}

export interface SharedSlotView {
  position: number;
  track_id: string | null;
  locked: boolean;
  notes: string | null;
  transition_score: number | null;
}

export interface SharedCurvePointView {
  position_sec: number;
  energy: number;
  label: string | null;
  is_slow_window_start: boolean;
  is_slow_window_end: boolean;
}

/** Public read-only projection of a shared set (no ids, no owner info). */
export interface SharedSetView {
  name: string;
  status: 'draft' | 'locked' | 'exported';
  vibe_theme: string | null;
  target_duration_sec: number | null;
  bpm_floor: number | null;
  bpm_ceiling: number | null;
  key_strictness: number;
  slots: SharedSlotView[];
  curve_points: SharedCurvePointView[];
}

/** OpenAPI expresses PaginatedResponse with `items: any[]`; keep this
 *  hand-crafted generic wrapper for type-safe consumer sites. */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  limit: number;
}
