import type { components } from '../api-types.generated';
import type { RequestStatus } from './types';

export interface AdminLlmAuditFilters {
  event_type?: string;
  actor_user_id?: number;
  target_connector_id?: number;
  days?: number;
  limit?: number;
  offset?: number;
}

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

export const PUBLIC_PAGE_MAX = 500;

export interface CollectLeaderboardRow {
  id: number;
  title: string;
  artist: string;
  artwork_url: string | null;
  vote_count: number;
  nickname: string | null;
  status: RequestStatus;
  created_at: string;
  bpm?: number | null;
  musical_key?: string | null;
  genre?: string | null;
  requester_verified?: boolean;
}

export interface CollectLeaderboardResponse { requests: CollectLeaderboardRow[]; total: number }
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
export type CollectionSettingsResponse = components['schemas']['CollectionSettingsResponse'];
export interface CollectionSyncResponse { queued: number }
export interface BulkReviewResponse { accepted: number; rejected: number; unchanged: number }

export interface LlmStreamChunk {
  text_delta?: string;
  tool_call_deltas?: Array<{
    index: number;
    id?: string | null;
    name?: string | null;
    input_json_fragment?: string;
  }>;
  stop_reason?: 'end_turn' | 'tool_use' | 'max_tokens' | 'error' | null;
  usage?: { prompt: number; completion: number } | null;
  done?: boolean;
}
