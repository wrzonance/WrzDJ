/**
 * PoolPanel component tests (issue #388) — source tagging visibility,
 * source filter + remove-by-source, multi-select removal, dedupe toast.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import type { PoolState } from '@/lib/api-types';
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
    created_at: '2026-06-09T00:00:00Z',
  },
];

const POOL: PoolState = { sources: SOURCES, tracks: TRACKS };

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.getPool.mockResolvedValue(POOL);
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
      pool: { sources: [SOURCES[1]], tracks: [TRACKS[1]] },
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
      pool: { sources: SOURCES, tracks: [] },
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
    fireEvent.click(screen.getByText('WrzDJ Event Requests'));
    // event picker modal: pick the event then import
    fireEvent.click(await screen.findByText('ABC123'));
    fireEvent.click(screen.getByText('Import requests'));
    await waitFor(() => expect(mockApi.importPoolEvent).toHaveBeenCalledWith(1, 7));
    expect(await screen.findByText('3 new · 2 de-duped')).toBeTruthy();
  });

  it('context menu offers per-track and per-source removal', async () => {
    mockApi.removePoolTracks.mockResolvedValue({
      removed: 1,
      pool: { sources: SOURCES, tracks: [TRACKS[1]] },
    });
    render(<PoolPanel setId={1} />);
    const row = await screen.findByText('Event Song');
    fireEvent.contextMenu(row);
    expect(screen.getByText(/Remove all from “Prom Night”/)).toBeTruthy();
    fireEvent.click(screen.getByText('Remove this track'));
    await waitFor(() => expect(mockApi.removePoolTracks).toHaveBeenCalledWith(1, [11]));
  });
});
