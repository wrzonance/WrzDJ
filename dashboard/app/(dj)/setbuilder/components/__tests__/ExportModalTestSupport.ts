import { beforeEach, afterEach, vi } from 'vitest';
import type { ExportPreflight, ExportSpotifyResult, ExportTidalResult, SetDetail } from '@/lib/api/types';
// ---- Mock the API singleton ----

const mockApi = vi.hoisted(() => ({
  exportPreflight: vi.fn(),
  exportSetToTidal: vi.fn(),
  exportSetToSpotify: vi.fn(),
  startSpotifyAuthorization: vi.fn(),
  getAppleMusicDeveloperToken: vi.fn(),
  linkAppleMusicAccount: vi.fn(),
  exportSetToAppleMusic: vi.fn(),
  reconcileAppleMusicExport: vi.fn(),
  exportSetFile: vi.fn(),
}));

export function getMockApi() {
  return mockApi;
}

vi.mock('@/lib/api', async importOriginal => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: mockApi,
}));

// ---- DOM helpers for download ----
// We stub URL.createObjectURL / revokeObjectURL + HTMLAnchorElement.prototype.click
// so triggerDownload doesn't crash in jsdom with navigation warnings.

export const createObjectURLSpy = vi.fn(() => 'blob:mock-url');
export const revokeObjectURLSpy = vi.fn();
Object.defineProperty(URL, 'createObjectURL', { value: createObjectURLSpy, writable: true });
Object.defineProperty(URL, 'revokeObjectURL', { value: revokeObjectURLSpy, writable: true });
HTMLAnchorElement.prototype.click = vi.fn();

// ---- Fixtures ----

export function makeSet(overrides: Partial<SetDetail> = {}): SetDetail {
  return {
    id: 42,
    name: 'Friday Wedding',
    event_id: null,
    status: 'draft',
    sharing_mode: 'private',
    share_token: null,
    vibe_theme: null,
    target_duration_sec: null,
    avg_transition_overlap_sec: 8,
    bpm_floor: null,
    bpm_ceiling: null,
    key_strictness: 0,
    tidal_playlist_id: null,
    spotify_playlist_id: null,
    apple_music_playlist_id: null,
    apple_music_export_uncertain: false,
    apple_music_export_recovery_playlist_id: null,
    exported_at: null,
    created_at: '2026-06-10T00:00:00Z',
    updated_at: '2026-06-10T00:00:00Z',
    ...overrides,
  };
}

export function makePreflightClean(target: ExportPreflight['target'] = 'rekordbox'): ExportPreflight {
  return {
    target,
    source: 'timeline',
    total: 10,
    resolved_count: 10,
    unresolved: [],
    tidal_connected: null,
    spotify_connected: null,
    apple_music_connected: null,
  };
}

export function makePreflightWithUnresolved(
  target: ExportPreflight['target'] = 'rekordbox'
): ExportPreflight {
  // Backend sets reason per target: tidal preflight → no_tidal_match,
  // file targets (rekordbox/m3u/txt) → missing_metadata.
  const reason = target === 'tidal'
    ? ('no_tidal_match' as const)
    : target === 'spotify'
      ? ('no_spotify_match' as const)
      : ('missing_metadata' as const);
  return {
    target,
    source: 'timeline',
    total: 12,
    resolved_count: 10,
    unresolved: [
      {
        position: 3,
        title: 'Ghost Track',
        artist: 'Unknown',
        track_id: 'bp-99',
        reason,
      },
      {
        position: 7,
        title: '',
        artist: '',
        track_id: 'bp-404',
        reason,
      },
    ],
    tidal_connected: null,
    spotify_connected: null,
    apple_music_connected: null,
  };
}

export const TIDAL_RESULT: ExportTidalResult = {
  playlist_id: 'pl-1',
  playlist_url: 'https://tidal.com/playlist/pl-1',
  added: 10,
  skipped: 0,
  exported_at: '2026-06-10T12:00:00Z',
  status: 'exported',
};

export const SPOTIFY_RESULT: ExportSpotifyResult = {
  playlist_id: 'spotify-pl-1',
  playlist_url: 'https://open.spotify.com/playlist/spotify-pl-1',
  added: 10,
  skipped: 0,
  exported_at: '2026-06-10T12:00:00Z',
  status: 'exported',
};

export const baseProps = {
  set: makeSet(),
  onClose: vi.fn(),
  onSetUpdated: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
  createObjectURLSpy.mockReturnValue('blob:mock-url');
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ============================================================
// 1. Platform picker — Apple Music export is available
// ============================================================
