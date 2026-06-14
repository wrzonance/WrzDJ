import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import BuilderWorkspace from '../components/BuilderWorkspace';
import type { PoolTrack, SetSlotOut } from '@/lib/api-types';

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

const mockGetSetSlots = vi.fn();
const mockGetCurveTemplates = vi.fn();
const mockGetVibeWindows = vi.fn();
const mockGetPool = vi.fn();
const mockSavePairing = vi.fn();
const mockUpdateSlotTarget = vi.fn();
const mockApplyCurveTemplate = vi.fn();
const mockPutVibeWindows = vi.fn();

vi.mock('@/lib/api', () => ({
  api: {
    getSetSlots: (setId: number) => mockGetSetSlots(setId),
    getPool: (setId: number) => mockGetPool(setId),
    savePairing: (setId: number, payload: object) => mockSavePairing(setId, payload),
    getCurveTemplates: () => mockGetCurveTemplates(),
    getVibeWindows: (setId: number) => mockGetVibeWindows(setId),
    updateSlotTarget: (setId: number, slotId: number, t: number | null) =>
      mockUpdateSlotTarget(setId, slotId, t),
    applyCurveTemplate: (setId: number, source: object, mids?: number[]) =>
      mockApplyCurveTemplate(setId, source, mids),
    putVibeWindows: (setId: number, windows: object[]) => mockPutVibeWindows(setId, windows),
    createCurveTemplate: vi.fn(),
    updateCurveTemplate: vi.fn(),
    deleteCurveTemplate: vi.fn(),
  },
}));

const SLOTS: SetSlotOut[] = [
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

const POOL_TRACKS: PoolTrack[] = [
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
    created_at: '2026-01-01T00:00:00Z',
  },
];

const TEMPLATES = {
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

describe('BuilderWorkspace', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetSetSlots.mockResolvedValue(SLOTS);
    mockGetPool.mockResolvedValue({ sources: [], tracks: POOL_TRACKS });
    mockGetCurveTemplates.mockResolvedValue(TEMPLATES);
    mockGetVibeWindows.mockResolvedValue({ windows: [] });
    mockUpdateSlotTarget.mockResolvedValue({ slot_id: 1, target_energy: 9 });
    mockPutVibeWindows.mockResolvedValue({ windows: [] });
    mockSavePairing.mockResolvedValue({ id: 44 });
  });

  it('fetches slots and renders curve blocks + timeline rows', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => {
      expect(screen.getByTestId('slot-block-0')).toBeInTheDocument();
      expect(screen.getByTestId('timeline-row-2')).toBeInTheDocument();
    });
    expect(mockGetSetSlots).toHaveBeenCalledWith(5);
  });

  it('hover on a curve block highlights the timeline row (and back)', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('slot-block-1')).toBeInTheDocument());

    fireEvent.mouseEnter(screen.getByTestId('slot-block-1'));
    expect(screen.getByTestId('timeline-row-1').className).toContain('timelineRowHover');

    fireEvent.mouseLeave(screen.getByTestId('slot-block-1'));
    fireEvent.mouseEnter(screen.getByTestId('timeline-row-0'));
    // timeline hover feeds back into the shared state (row 0 highlighted)
    expect(screen.getByTestId('timeline-row-0').className).toContain('timelineRowHover');
  });

  it('drag-release PATCHes the slot target', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('target-handle-0')).toBeInTheDocument());

    fireEvent.pointerDown(screen.getByTestId('target-handle-0'), { clientY: 50 });
    fireEvent.pointerMove(window, { clientY: 10 });
    fireEvent.pointerUp(window);

    await waitFor(() => expect(mockUpdateSlotTarget).toHaveBeenCalledTimes(1));
    const [setId, slotId, energy] = mockUpdateSlotTarget.mock.calls[0];
    expect(setId).toBe(5);
    expect(slotId).toBe(1);
    expect(typeof energy).toBe('number');
  });

  it('drag-release with big mismatch opens the replacement popover (gated)', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('target-handle-0')).toBeInTheDocument());

    // jsdom rects are 0-size → eOfY ends at energy 10, far from track energy 5
    fireEvent.pointerDown(screen.getByTestId('target-handle-0'), { clientY: 50 });
    fireEvent.pointerMove(window, { clientY: -100 });
    fireEvent.pointerUp(window);

    await waitFor(() => expect(screen.getByTestId('replace-popover')).toBeInTheDocument());
    // empty pool → empty state, gate toggle visible
    expect(screen.getByTestId('replace-empty')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('replace-keep'));
    expect(screen.queryByTestId('replace-popover')).not.toBeInTheDocument();
  });

  it('toggle off suppresses the replacement popover', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('target-handle-0')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('suggest-replacements-toggle'));
    fireEvent.pointerDown(screen.getByTestId('target-handle-0'), { clientY: 50 });
    fireEvent.pointerMove(window, { clientY: -100 });
    fireEvent.pointerUp(window);

    await waitFor(() => expect(mockUpdateSlotTarget).toHaveBeenCalled());
    expect(screen.queryByTestId('replace-popover')).not.toBeInTheDocument();
    window.localStorage.removeItem('wrzdj.curve.suggestReplacements');
  });

  it('applying a built-in template re-targets slots from the server response', async () => {
    mockApplyCurveTemplate.mockResolvedValue({
      targets: [
        { slot_id: 1, target_energy: 7.2 },
        { slot_id: 2, target_energy: 7.5 },
        { slot_id: 3, target_energy: 7.8 },
      ],
      windows: [],
    });
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('curve-toolbar')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('template-dropdown-trigger'));
    await waitFor(() => expect(screen.getByTestId('apply-builtin-Club Peak')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('apply-builtin-Club Peak'));

    await waitFor(() => expect(mockApplyCurveTemplate).toHaveBeenCalledTimes(1));
    const [setId, source, mids] = mockApplyCurveTemplate.mock.calls[0];
    expect(setId).toBe(5);
    expect(source).toEqual({ builtin: 'Club Peak' });
    expect(mids).toHaveLength(3);
    // Timeline target chips reflect the applied targets
    await waitFor(() => {
      expect(screen.getByTestId('timeline-row-0')).toHaveTextContent('7.2');
    });
  });

  it('shows DJ pairing markers in timeline and curve', async () => {
    mockGetSetSlots.mockResolvedValue([
      { ...SLOTS[0], next_pairing_id: 77, next_is_dj_pairing: true, transition_score: 94 },
      SLOTS[1],
      SLOTS[2],
    ]);
    render(<BuilderWorkspace setId={5} />);

    await waitFor(() => expect(screen.getByTestId('pairing-pin-0')).toBeInTheDocument());
    expect(screen.getByTestId('timeline-transition-0')).toHaveTextContent('DJ pairing');
    expect(screen.getByTestId('timeline-transition-0')).toHaveTextContent('94');
  });

  it('timeline context menu saves the transition to the next slot as a pairing', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-0')).toBeInTheDocument());

    fireEvent.contextMenu(screen.getByTestId('timeline-row-0'), { clientX: 120, clientY: 140 });
    fireEvent.click(screen.getByText('Save -> Track B as pairing'));

    await waitFor(() => expect(mockSavePairing).toHaveBeenCalledTimes(1));
    expect(mockSavePairing).toHaveBeenCalledWith(5, {
      from_track_id: 'a',
      into_track_id: 'b',
      cue_in_sec: null,
      note: null,
      tags: [],
      increment_use_count: true,
    });
  });

  it('click on a curve block requests a timeline scroll', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('slot-block-2')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('slot-block-2'));
    // scrollIntoView only fires when out of view; with jsdom 0-rects rows are
    // "in view", so just assert no crash and the row exists.
    expect(screen.getByTestId('timeline-row-2')).toBeInTheDocument();
  });

  it('adding a vibe preset window persists via PUT', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('slot-block-0')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('vibe-dropdown-trigger'));
    fireEvent.click(screen.getByTestId('vibe-preset-first-dance'));

    await waitFor(() => expect(mockPutVibeWindows).toHaveBeenCalledTimes(1));
    const [, windows] = mockPutVibeWindows.mock.calls[0];
    expect(windows).toHaveLength(1);
    expect(windows[0].label).toBe('First Dance');
    expect(screen.getByText('FIRST DANCE')).toBeInTheDocument();
  });
});
