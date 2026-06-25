/**
 * PoolPanel component tests (issue #388) — source tagging visibility,
 * source filter + remove-by-source, multi-select removal, dedupe toast.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { ApiError } from '@/lib/api';
import type {
  PoolState,
  PoolVibesState,
  TrackVibeState,
  VibeEnrichmentResult,
} from '@/lib/api-types';
import PoolPanel from '../PoolPanel';

const mockApi = vi.hoisted(() => ({
  getPool: vi.fn(),
  getBuilderPlaylists: vi.fn(),
  importPoolEvent: vi.fn(),
  importPoolManual: vi.fn(),
  removePoolTracks: vi.fn(),
  removePoolSource: vi.fn(),
  getEvents: vi.fn(),
  search: vi.fn(),
  getPoolVibes: vi.fn(),
  enrichPoolVibes: vi.fn(),
  agreePoolVibe: vi.fn(),
  overridePoolVibe: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/api')>();
  return { api: mockApi, ApiError: original.ApiError };
});

const SOURCES = [
  {
    id: 1,
    kind: 'event' as const,
    external_ref: '7',
    label: 'Prom Night',
    meta: 'WrzDJ event requests',
    created_at: '2026-06-09T00:00:00Z',
  },
  {
    id: 2,
    kind: 'tidal' as const,
    external_ref: 'pl-1',
    label: 'Friday Warmup',
    meta: 'Tidal playlist',
    created_at: '2026-06-09T00:00:00Z',
  },
];

const TRACKS = [
  {
    id: 11,
    source_id: 1,
    track_id: 'request:1',
    title: 'Event Song',
    artist: 'Event Artist',
    album: null,
    genre: 'House',
    bpm: 126,
    key: 'Am',
    camelot: '8A',
    energy: 7,
    isrc: null,
    duration_sec: null,
    artwork_url: null,
    enrichment_status: 'enriched' as const,
    created_at: '2026-06-09T00:00:00Z',
  },
  {
    id: 12,
    source_id: 2,
    track_id: 'tidal:9',
    title: 'Tidal Song',
    artist: 'Tidal Artist',
    album: null,
    genre: null,
    bpm: null,
    key: null,
    camelot: null,
    energy: null,
    isrc: null,
    duration_sec: null,
    artwork_url: null,
    enrichment_status: 'pending' as const,
    created_at: '2026-06-09T00:00:00Z',
  },
];

const POOL: PoolState = {
  sources: SOURCES,
  tracks: TRACKS,
  enrichment: { total: 2, enriched: 1, failed: 0, pending: 1, in_progress: true },
  runtime_sec: 0,
};

const ENRICHED_POOL: PoolState = {
  sources: SOURCES,
  tracks: TRACKS.map((track) => ({ ...track, enrichment_status: 'enriched' as const })),
  enrichment: { total: 2, enriched: 2, failed: 0, pending: 0, in_progress: false },
  runtime_sec: 0,
};

function poolState(sources: PoolState['sources'], tracks: PoolState['tracks']): PoolState {
  const enriched = tracks.filter((track) => track.enrichment_status === 'enriched').length;
  const failed = tracks.filter((track) => track.enrichment_status === 'failed').length;
  const pending = tracks.filter((track) => track.enrichment_status === 'pending').length;
  return {
    sources,
    tracks,
    enrichment: { total: tracks.length, enriched, failed, pending, in_progress: pending > 0 },
    runtime_sec: 0,
  };
}

// --- Vibe fixtures (issue #391) ---

const VIBE_STATE: TrackVibeState = {
  pool_track_id: 11,
  vibe_key: 'event artist|event song',
  own: { energy: 9, mood: null },
  community: null,
  llm: null,
  resolved: { energy: 9, energy_source: 'own', mood: null, mood_source: null },
};

const POOL_VIBES: PoolVibesState = { tracks: [VIBE_STATE] };

const COMMUNITY_VIBE_STATE: TrackVibeState = {
  ...VIBE_STATE,
  own: null,
  community: { energy: 7, mood: 'dark', sample_size: 3 },
  resolved: { energy: 7, energy_source: 'community', mood: 'dark', mood_source: 'community' },
};

const ENRICHED_VIBE_STATE: TrackVibeState = {
  ...VIBE_STATE,
  llm: {
    energy: 5,
    mood: 'happy',
    confidence: 0.92,
    low_confidence: false,
    llm_provider: 'anthropic_apikey',
    llm_model: 'claude-haiku-4-5',
    dance_floor: null,
    era: null,
    sing_along: null,
    transitional_role: null,
  },
  resolved: { energy: 9, energy_source: 'own', mood: 'happy', mood_source: 'llm' },
};

const ENRICH_RESULT: VibeEnrichmentResult = {
  enriched: 2,
  cached: 0,
  failed: 0,
  llm_calls: 2,
  vibes: { tracks: [ENRICHED_VIBE_STATE] },
};

const OVERRIDDEN_VIBE_STATE: TrackVibeState = {
  ...COMMUNITY_VIBE_STATE,
  own: { energy: 8, mood: 'gritty' },
  resolved: { energy: 8, energy_source: 'own', mood: 'gritty', mood_source: 'own' },
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.getPool.mockResolvedValue(POOL);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('PoolPanel', () => {
  it('renders tracks with source chips and badges', async () => {
    render(<PoolPanel setId={1} />);
    expect(await screen.findByText('Event Song')).toBeTruthy();
    expect(screen.getByText('Tidal Song')).toBeTruthy();
    // source chip labels visible on rows (chip + accordion row)
    expect(screen.getAllByText('Prom Night').length).toBeGreaterThanOrEqual(2);
    // camelot + bpm badges
    expect(screen.getByText('8A')).toBeTruthy();
    expect(screen.getByText('126')).toBeTruthy();
  });

  it('renders enrichment progress while pool tracks are pending', async () => {
    render(<PoolPanel setId={1} />);

    expect(await screen.findByText('Enriching 1/2...')).toBeTruthy();
    const bar = screen.getByRole('progressbar', { name: 'Pool enrichment progress' });
    expect(bar).toHaveAttribute('aria-valuenow', '50');
    expect(screen.getByText('1 pending')).toBeTruthy();
  });

  it('polls pool state while enrichment is pending and stops at completion', async () => {
    vi.useFakeTimers();
    mockApi.getPool
      .mockResolvedValueOnce(POOL)
      .mockResolvedValueOnce(ENRICHED_POOL)
      .mockResolvedValue(ENRICHED_POOL);

    render(<PoolPanel setId={1} />);

    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByText('Enriching 1/2...')).toBeTruthy();
    expect(mockApi.getPool).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(2500);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(mockApi.getPool).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/Enriching/)).toBeNull();

    await act(async () => {
      vi.advanceTimersByTime(5000);
      await Promise.resolve();
    });
    expect(mockApi.getPool).toHaveBeenCalledTimes(2);
  });

  it('writes a pool-track drag payload when dragging a track row', async () => {
    // Regression for 75050c04: the production pool row port must preserve drag payloads.
    render(<PoolPanel setId={1} />);
    await screen.findByText('Event Song');
    const row = screen.getByTestId('pool-track-11');
    const dataTransfer = {
      effectAllowed: '',
      setData: vi.fn(),
    };

    fireEvent.dragStart(row, { dataTransfer });

    expect(dataTransfer.effectAllowed).toBe('copy');
    expect(dataTransfer.setData).toHaveBeenCalledWith(
      'application/x-wrzdj-pool-track',
      JSON.stringify({ poolTrackId: 11 }),
    );
  });

  it('filters the list when a source row is clicked', async () => {
    render(<PoolPanel setId={1} />);
    await screen.findByText('Event Song');
    fireEvent.click(screen.getAllByTitle('Click to filter pool by this source')[0]);
    // first source row main button is Prom Night — Tidal Song should disappear
    expect(screen.queryByText('Tidal Song')).toBeNull();
    expect(screen.getByText('Event Song')).toBeTruthy();
    expect(screen.getByText('filtered · clear')).toBeTruthy();
  });

  it('removes a source via the hover × and updates state from response', async () => {
    mockApi.removePoolSource.mockResolvedValue({
      removed: 1,
      pool: poolState([SOURCES[1]], [TRACKS[1]]),
    });
    render(<PoolPanel setId={1} />);
    await screen.findByText('Event Song');
    fireEvent.click(screen.getByLabelText('Remove source Prom Night'));
    await waitFor(() => expect(mockApi.removePoolSource).toHaveBeenCalledWith(1, 1));
    await waitFor(() => expect(screen.queryByText('Event Song')).toBeNull());
    expect(screen.getByText('Tidal Song')).toBeTruthy();
    expect(screen.getByText('Removed source · 1 tracks')).toBeTruthy();
  });

  it('multi-select: select-all-visible then remove calls removePoolTracks', async () => {
    mockApi.removePoolTracks.mockResolvedValue({
      removed: 2,
      pool: poolState(SOURCES, []),
    });
    render(<PoolPanel setId={1} />);
    await screen.findByText('Event Song');
    fireEvent.click(screen.getByTitle('Multi-select tracks'));
    fireEvent.click(screen.getByText('Select all visible'));
    fireEvent.click(screen.getByText('Remove 2'));
    await waitFor(() =>
      expect(mockApi.removePoolTracks).toHaveBeenCalledWith(1, expect.arrayContaining([11, 12]))
    );
    await waitFor(() => expect(screen.queryByText('Event Song')).toBeNull());
  });

  it('type tabs show live counts and filter by source kind', async () => {
    render(<PoolPanel setId={1} />);
    await screen.findByText('Event Song');
    const tidalTab = screen.getByRole('button', { name: /Tidal 1/ });
    fireEvent.click(tidalTab);
    expect(screen.queryByText('Event Song')).toBeNull();
    expect(screen.getByText('Tidal Song')).toBeTruthy();
  });

  it('import flow surfaces the dedupe toast "N new · M de-duped"', async () => {
    mockApi.getEvents.mockResolvedValue([
      { id: 7, code: 'ABC123', name: 'Prom Night' },
    ]);
    mockApi.importPoolEvent.mockResolvedValue({
      added: 3,
      deduped: 2,
      source: SOURCES[0],
      pool: POOL,
    });
    render(<PoolPanel setId={1} />);
    await screen.findByText('Event Song');
    fireEvent.click(screen.getByText('+ Add'));
    const eventImportItem = screen.getByText('WrzDJ Event Requests').closest('button')!;
    fireEvent.mouseDown(eventImportItem);
    fireEvent.click(eventImportItem);
    // event picker modal: pick the event then import
    fireEvent.click(await screen.findByLabelText('Select Prom Night'));
    fireEvent.click(screen.getByText('Import requests'));
    await waitFor(() => expect(mockApi.importPoolEvent).toHaveBeenCalledWith(1, 7));
    expect(await screen.findByText('3 new · 2 de-duped')).toBeTruthy();
  });

  it('opens every Add-menu import modal after the browser mousedown/click sequence', async () => {
    mockApi.getEvents.mockResolvedValue([]);
    mockApi.getBuilderPlaylists.mockResolvedValue({
      tidal_connected: true,
      beatport_connected: true,
      tidal: [],
      beatport: [],
    });
    render(<PoolPanel setId={1} />);
    await screen.findByText('Event Song');

    const cases = [
      ['WrzDJ Event Requests', 'Import event requests'],
      ['Tidal Playlist', 'Import Tidal playlist'],
      ['Beatport Playlist', 'Import Beatport playlist'],
      ['Public Playlist URL', 'Import public playlist'],
      ['Add single track', 'Add a single track'],
    ] as const;

    for (const [menuLabel, modalTitle] of cases) {
      fireEvent.click(screen.getByText('+ Add'));
      const menuItem = screen.getByText(menuLabel).closest('button')!;
      fireEvent.mouseDown(menuItem);
      fireEvent.click(menuItem);

      expect(await screen.findByRole('dialog')).toBeTruthy();
      expect(screen.getByText(modalTitle)).toBeTruthy();
      fireEvent.click(screen.getByLabelText('Close'));
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    }
  });

  it('context menu offers per-track and per-source removal', async () => {
    mockApi.removePoolTracks.mockResolvedValue({
      removed: 1,
      pool: poolState(SOURCES, [TRACKS[1]]),
    });
    render(<PoolPanel setId={1} />);
    const row = await screen.findByText('Event Song');
    fireEvent.contextMenu(row);
    expect(screen.getByText(/Remove all from “Prom Night”/)).toBeTruthy();
    fireEvent.click(screen.getByText('Remove this track'));
    await waitFor(() => expect(mockApi.removePoolTracks).toHaveBeenCalledWith(1, [11]));
  });

  it('Vibes toggle fetches once, renders chips on rows, hides on toggle-off', async () => {
    mockApi.getPoolVibes.mockResolvedValue(POOL_VIBES);
    render(<PoolPanel setId={1} />);
    await screen.findByText('Event Song');

    fireEvent.click(screen.getByText('Vibes'));
    // chips render on the track row once the fetch resolves
    expect(await screen.findByLabelText('Your vibe: energy 9')).toBeTruthy();
    expect(screen.getByLabelText('Community vibe: not set')).toBeTruthy();
    expect(screen.getByLabelText('AI vibe: not set')).toBeTruthy();
    expect(mockApi.getPoolVibes).toHaveBeenCalledTimes(1);
    expect(mockApi.getPoolVibes).toHaveBeenCalledWith(1);

    // toggle off hides the chips
    fireEvent.click(screen.getByText('Vibes'));
    expect(screen.queryByLabelText('Your vibe: energy 9')).toBeNull();

    // toggle back on does NOT refetch
    fireEvent.click(screen.getByText('Vibes'));
    expect(await screen.findByLabelText('Your vibe: energy 9')).toBeTruthy();
    expect(mockApi.getPoolVibes).toHaveBeenCalledTimes(1);
  });

  it('failed initial vibes fetch can be retried on next toggle-on', async () => {
    mockApi.getPoolVibes.mockRejectedValueOnce(new Error('boom'));
    mockApi.getPoolVibes.mockResolvedValueOnce(POOL_VIBES);
    render(<PoolPanel setId={1} />);
    await screen.findByText('Event Song');

    // first toggle-on: fetch fails, toast shown, no chips
    fireEvent.click(screen.getByText('Vibes'));
    expect(await screen.findByText('Failed to load vibes')).toBeTruthy();
    expect(screen.queryByLabelText('Your vibe: energy 9')).toBeNull();

    // toggle off, then on again: fetch retries and succeeds
    fireEvent.click(screen.getByText('Vibes'));
    fireEvent.click(screen.getByText('Vibes'));
    expect(await screen.findByLabelText('Your vibe: energy 9')).toBeTruthy();
    expect(mockApi.getPoolVibes).toHaveBeenCalledTimes(2);
  });

  it('Analyze is gated behind Vibes, enriches, updates chips, and toasts counts', async () => {
    mockApi.getPoolVibes.mockResolvedValue(POOL_VIBES);
    mockApi.enrichPoolVibes.mockResolvedValue(ENRICH_RESULT);
    render(<PoolPanel setId={1} />);
    await screen.findByText('Event Song');

    // Analyze hidden until vibes are shown
    expect(screen.queryByText('Analyze')).toBeNull();

    fireEvent.click(screen.getByText('Vibes'));
    // button reads "Analyzing…" while the initial vibe fetch is busy,
    // then settles to "Analyze" once it resolves
    fireEvent.click(await screen.findByText('Analyze'));
    await waitFor(() => expect(mockApi.enrichPoolVibes).toHaveBeenCalledWith(1));
    expect(await screen.findByText(/2 analyzed · 0 cached · 0 failed/)).toBeTruthy();
    // chips updated from the enrichment result — AI tier now populated
    expect(screen.getByLabelText('AI vibe: energy 5, mood happy')).toBeTruthy();
  });

  it('vibe controls agree and tweak pool-row ratings through the API', async () => {
    mockApi.getPoolVibes.mockResolvedValue({ tracks: [COMMUNITY_VIBE_STATE] });
    mockApi.agreePoolVibe.mockResolvedValue({ tracks: [COMMUNITY_VIBE_STATE] });
    mockApi.overridePoolVibe.mockResolvedValue({ tracks: [OVERRIDDEN_VIBE_STATE] });
    render(<PoolPanel setId={1} />);
    await screen.findByText('Event Song');

    fireEvent.click(screen.getByText('Vibes'));
    expect(await screen.findByLabelText('Vibe source: community consensus')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Agree' }));
    await waitFor(() => expect(mockApi.agreePoolVibe).toHaveBeenCalledWith(1, 11));
    expect(await screen.findByText('Vibe upvoted')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Tweak' }));
    fireEvent.change(screen.getByLabelText('Energy'), { target: { value: '8' } });
    fireEvent.change(screen.getByLabelText('Mood'), { target: { value: 'gritty' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(mockApi.overridePoolVibe).toHaveBeenCalledWith(1, 11, {
        energy: 8,
        mood: 'gritty',
      })
    );
    expect(await screen.findByLabelText('Your vibe: energy 8, mood gritty')).toBeTruthy();
  });

  it('tracks overlapping vibe writes per pool track', async () => {
    const secondCommunityVibe: TrackVibeState = {
      ...COMMUNITY_VIBE_STATE,
      pool_track_id: 12,
      vibe_key: 'tidal artist|tidal song',
    };
    const firstWrite = deferred<PoolVibesState>();
    const secondWrite = deferred<PoolVibesState>();
    mockApi.getPoolVibes.mockResolvedValue({
      tracks: [COMMUNITY_VIBE_STATE, secondCommunityVibe],
    });
    mockApi.agreePoolVibe
      .mockReturnValueOnce(firstWrite.promise)
      .mockReturnValueOnce(secondWrite.promise);
    render(<PoolPanel setId={1} />);
    await screen.findByText('Event Song');

    fireEvent.click(screen.getByText('Vibes'));
    const eventRow = await screen.findByTestId('pool-track-11');
    const tidalRow = screen.getByTestId('pool-track-12');
    const eventAgree = within(eventRow).getByRole('button', { name: 'Agree' });
    const tidalAgree = within(tidalRow).getByRole('button', { name: 'Agree' });

    fireEvent.click(eventAgree);
    await waitFor(() => expect((eventAgree as HTMLButtonElement).disabled).toBe(true));
    fireEvent.click(tidalAgree);

    await waitFor(() => expect((tidalAgree as HTMLButtonElement).disabled).toBe(true));
    expect((eventAgree as HTMLButtonElement).disabled).toBe(true);

    await act(async () => {
      firstWrite.resolve({ tracks: [COMMUNITY_VIBE_STATE, secondCommunityVibe] });
      await firstWrite.promise;
    });

    await waitFor(() => expect((eventAgree as HTMLButtonElement).disabled).toBe(false));
    expect((tidalAgree as HTMLButtonElement).disabled).toBe(true);

    await act(async () => {
      secondWrite.resolve({ tracks: [COMMUNITY_VIBE_STATE, secondCommunityVibe] });
      await secondWrite.promise;
    });
    await waitFor(() => expect((tidalAgree as HTMLButtonElement).disabled).toBe(false));
  });

  it('keeps the tweak form open when override save fails', async () => {
    mockApi.getPoolVibes.mockResolvedValue({ tracks: [COMMUNITY_VIBE_STATE] });
    mockApi.overridePoolVibe.mockRejectedValueOnce(new ApiError('Invalid vibe override', 422));
    render(<PoolPanel setId={1} />);
    await screen.findByText('Event Song');

    fireEvent.click(screen.getByText('Vibes'));
    fireEvent.click(await screen.findByRole('button', { name: 'Tweak' }));
    fireEvent.change(screen.getByLabelText('Energy'), { target: { value: '8' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(mockApi.overridePoolVibe).toHaveBeenCalledWith(1, 11, {
      energy: 8,
      mood: 'dark',
    }));
    expect(await screen.findByText('Invalid vibe override')).toBeTruthy();
    expect(screen.getByLabelText('Energy')).toBeTruthy();
  });

  it('analyze failure surfaces ApiError 400 message, generic text otherwise', async () => {
    mockApi.getPoolVibes.mockResolvedValue(POOL_VIBES);
    mockApi.enrichPoolVibes.mockRejectedValueOnce(
      new ApiError('No AI connector configured — connect one in Settings → AI.', 400)
    );
    render(<PoolPanel setId={1} />);
    await screen.findByText('Event Song');

    fireEvent.click(screen.getByText('Vibes'));
    fireEvent.click(await screen.findByText('Analyze'));
    expect(
      await screen.findByText('No AI connector configured — connect one in Settings → AI.')
    ).toBeTruthy();

    // non-ApiError rejection falls back to the generic toast
    mockApi.enrichPoolVibes.mockRejectedValueOnce(new Error('boom'));
    fireEvent.click(await screen.findByText('Analyze'));
    expect(await screen.findByText('Vibe analysis failed')).toBeTruthy();
  });
});
