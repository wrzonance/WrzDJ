import { beforeAll, beforeEach, afterEach, vi } from 'vitest';
import type { PoolTrack, SetDocumentSnapshot, SetSlotOut } from '@/lib/api/types';
beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  Element.prototype.scrollIntoView = vi.fn();
  // In-memory localStorage (node 22 jsdom env lacks one without a flag)
  const store = new Map<string, string>();
  Object.defineProperty(window, 'localStorage', {
    value: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, String(v)),
      removeItem: (k: string) => void store.delete(k),
      clear: () => store.clear(),
    },
    writable: true,
    configurable: true,
  });
});

export const mockGetSetSlots = vi.fn();
export const mockGetCurveTemplates = vi.fn();
export const mockGetVibeWindows = vi.fn();
export const mockGetPool = vi.fn();
export const mockGetSetDocument = vi.fn();
export const mockPutSetDocument = vi.fn();
export const mockSavePairing = vi.fn();
export const mockUpdateSlotTarget = vi.fn();
export const mockApplyCurveTemplate = vi.fn();
export const mockPutVibeWindows = vi.fn();
export const mockGetTransportStatus = vi.fn();
export const mockSendTransportCommand = vi.fn();

vi.mock('@/lib/api', () => ({
  api: {
    getSetSlots: (setId: number) => mockGetSetSlots(setId),
    getPool: (setId: number) => mockGetPool(setId),
    getSetDocument: (setId: number) => mockGetSetDocument(setId),
    putSetDocument: (setId: number, snapshot: SetDocumentSnapshot) =>
      mockPutSetDocument(setId, snapshot),
    savePairing: (setId: number, payload: object) => mockSavePairing(setId, payload),
    getCurveTemplates: () => mockGetCurveTemplates(),
    getVibeWindows: (setId: number) => mockGetVibeWindows(setId),
    updateSlotTarget: (setId: number, slotId: number, t: number | null) =>
      mockUpdateSlotTarget(setId, slotId, t),
    applyCurveTemplate: (setId: number, source: object, mids?: number[]) =>
      mockApplyCurveTemplate(setId, source, mids),
    putVibeWindows: (setId: number, windows: object[]) => mockPutVibeWindows(setId, windows),
    getTransportStatus: (setId: number) => mockGetTransportStatus(setId),
    sendTransportCommand: (setId: number, payload: object) =>
      mockSendTransportCommand(setId, payload),
    createCurveTemplate: vi.fn(),
    updateCurveTemplate: vi.fn(),
    deleteCurveTemplate: vi.fn(),
  },
}));

export const SLOTS: SetSlotOut[] = [
  {
    id: 1,
    position: 0,
    track_id: 'a',
    locked: false,
    target_energy: null,
    notes: null,
    transition_score: null,
    transition_warnings: null,
    pool_track_id: null,
    title: null,
    artist: null,
    bpm: null,
    key: null,
    camelot: null,
    energy: null,
    duration_sec: null,
    next_pairing_id: null,
    next_is_dj_pairing: false,
  },
  {
    id: 2,
    position: 1,
    track_id: 'b',
    locked: false,
    target_energy: 7,
    notes: null,
    transition_score: null,
    transition_warnings: null,
    pool_track_id: null,
    title: null,
    artist: null,
    bpm: null,
    key: null,
    camelot: null,
    energy: null,
    duration_sec: null,
    next_pairing_id: null,
    next_is_dj_pairing: false,
  },
  {
    id: 3,
    position: 2,
    track_id: 'c',
    locked: false,
    target_energy: null,
    notes: null,
    transition_score: null,
    transition_warnings: null,
    pool_track_id: null,
    title: null,
    artist: null,
    bpm: null,
    key: null,
    camelot: null,
    energy: null,
    duration_sec: null,
    next_pairing_id: null,
    next_is_dj_pairing: false,
  },
];

export const POOL_TRACKS: PoolTrack[] = [
  {
    id: 11,
    source_id: 1,
    track_id: 'a',
    title: 'Track A',
    artist: 'Artist A',
    album: null,
    bpm: 120,
    camelot: '8A',
    key: '8A',
    energy: 5,
    duration_sec: 201,
    genre: null,
    isrc: null,
    artwork_url: null,
    enrichment_status: 'enriched',
    created_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 12,
    source_id: 1,
    track_id: 'b',
    title: 'Track B',
    artist: 'Artist B',
    album: null,
    bpm: 124,
    camelot: '9A',
    key: '9A',
    energy: 7,
    duration_sec: 211,
    genre: null,
    isrc: null,
    artwork_url: null,
    enrichment_status: 'enriched',
    created_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 13,
    source_id: 1,
    track_id: 'c',
    title: 'Track C',
    artist: 'Artist C',
    album: null,
    bpm: 128,
    camelot: '10A',
    key: '10A',
    energy: 6,
    duration_sec: 221,
    genre: null,
    isrc: null,
    artwork_url: null,
    enrichment_status: 'enriched',
    created_at: '2026-01-01T00:00:00Z',
  },
];

export function largeSlots(count: number): SetSlotOut[] {
  return Array.from({ length: count }, (_, idx) => ({
    ...SLOTS[idx % SLOTS.length],
    id: 1_000 + idx,
    position: idx,
    track_id: `large-${idx}`,
    target_energy: idx % 3 === 0 ? null : 5 + (idx % 5),
    title: null,
    artist: null,
    bpm: null,
    key: null,
    camelot: null,
    energy: null,
    duration_sec: null,
    next_pairing_id: null,
    next_is_dj_pairing: false,
  }));
}

export function largePoolTracks(count: number): PoolTrack[] {
  return Array.from({ length: count }, (_, idx) => ({
    ...POOL_TRACKS[idx % POOL_TRACKS.length],
    id: 2_000 + idx,
    track_id: `large-${idx}`,
    title: `Large Track ${idx}`,
    artist: `Large Artist ${idx}`,
    bpm: 118 + (idx % 24),
    camelot: `${(idx % 12) + 1}A`,
    key: `${(idx % 12) + 1}A`,
    energy: 4 + (idx % 6),
    duration_sec: 180 + (idx % 90),
    created_at: '2026-01-01T00:00:00Z',
  }));
}

export const EXTRA_POOL_TRACK: PoolTrack = {
  id: 14,
  source_id: 1,
  track_id: 'd',
  title: 'Track D',
  artist: 'Artist D',
  album: null,
  bpm: 130,
  camelot: '11A',
  key: '11A',
  energy: 8,
  duration_sec: 231,
  genre: null,
  isrc: null,
  artwork_url: null,
  enrichment_status: 'enriched',
  created_at: '2026-01-01T00:00:00Z',
};

export const SYNTHETIC_POOL_TRACK: PoolTrack = {
  id: 15,
  source_id: 1,
  track_id: null,
  title: 'Manual Track',
  artist: 'Manual Artist',
  album: null,
  bpm: 124,
  camelot: null,
  key: null,
  energy: null,
  duration_sec: null,
  genre: null,
  isrc: null,
  artwork_url: null,
  enrichment_status: 'pending',
  created_at: '2026-01-01T00:00:00Z',
};

export function cloneDocument(doc: SetDocumentSnapshot): SetDocumentSnapshot {
  return JSON.parse(JSON.stringify(doc)) as SetDocumentSnapshot;
}

export function documentSnapshot(): SetDocumentSnapshot {
  return {
    settings: {
      vibe_theme: null,
      target_duration_sec: null,
      bpm_floor: null,
      bpm_ceiling: null,
      key_strictness: 0.2,
    },
    slots: SLOTS.map((slot) => ({
      id: slot.id,
      position: slot.position,
      track_id: slot.track_id,
      locked: slot.locked,
      notes: slot.notes,
      transition_score: slot.transition_score,
      transition_warnings: slot.transition_warnings,
      target_energy: slot.target_energy,
    })),
    curve_points: [],
    pool: {
      sources: [
        {
          id: 1,
          kind: 'tidal',
          external_ref: 'pl-1',
          label: 'Friday Warmup',
          meta: 'Tidal playlist',
          created_at: '2026-01-01T00:00:00Z',
        },
      ],
      tracks: [...POOL_TRACKS, EXTRA_POOL_TRACK, SYNTHETIC_POOL_TRACK].map((track) => ({
        ...track,
        dedupe_sig: `sig-${track.id}`,
      })),
    },
  } as SetDocumentSnapshot;
}

export function documentWithVibeWindow(label: string): SetDocumentSnapshot {
  return {
    ...documentSnapshot(),
    curve_points: [
      {
        id: 1,
        position_sec: 0,
        energy: 3,
        label,
        is_slow_window_start: true,
        is_slow_window_end: false,
      },
      {
        id: 2,
        position_sec: 60,
        energy: 3,
        label: null,
        is_slow_window_start: false,
        is_slow_window_end: true,
      },
    ],
  };
}

export const TEMPLATES = {
  builtin: [
    {
      name: 'Club Peak',
      points: [
        { t: 0, e: 7, label: 'Warm', slow_start: false, slow_end: false },
        { t: 1, e: 8, label: 'Cool', slow_start: false, slow_end: false },
      ],
    },
  ],
  user: [],
};



beforeEach(() => {
    vi.clearAllMocks();
    mockGetSetSlots.mockResolvedValue(SLOTS);
    mockGetPool.mockResolvedValue({ sources: [], tracks: POOL_TRACKS });
    mockGetSetDocument.mockResolvedValue(cloneDocument(documentSnapshot()));
    mockPutSetDocument.mockImplementation((_setId: number, snapshot: SetDocumentSnapshot) =>
      Promise.resolve(cloneDocument(snapshot)),
    );
    mockGetCurveTemplates.mockResolvedValue(TEMPLATES);
    mockGetVibeWindows.mockReset().mockResolvedValue({ windows: [] });
    mockUpdateSlotTarget.mockResolvedValue({ slot_id: 1, target_energy: 9 });
    mockPutVibeWindows.mockResolvedValue({ windows: [] });
    mockSavePairing.mockResolvedValue({ id: 44 });
    mockGetTransportStatus.mockResolvedValue({
      connected: true,
      active_source: 'setbuilder:tidal',
      device_name: 'Bridge App',
      last_seen: null,
    });
    mockSendTransportCommand.mockResolvedValue({
      command_id: 'cmd-1',
      command_type: 'setbuilder_transport',
      action: 'play',
      active_source: 'tidal',
    });
  });

afterEach(() => {
    vi.useRealTimers();
    window.localStorage.clear();
  });
