export interface PreEventEventShape {
  code: string;
  name: string;
  collection_opens_at: string | null;
  live_starts_at: string | null;
  submission_cap_per_guest: number;
  collection_phase_override: 'force_collection' | 'force_live' | null;
  phase: 'pre_announce' | 'collection' | 'live' | 'closed';
  tidal_sync_enabled: boolean;
  tidal_collection_playlist_id: string | null;
  tidal_collection_bidirectional: boolean;
}
