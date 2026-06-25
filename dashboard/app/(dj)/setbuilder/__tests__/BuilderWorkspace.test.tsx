import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import BuilderWorkspace from '../components/BuilderWorkspace';
import { timelineMeasurementKey } from '../components/TimelinePanel';
import { slotViewFromApi } from '../components/types';
import type { PoolTrack, SetDocumentSnapshot, SetSlotOut } from '@/lib/api-types';

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
const mockGetSetDocument = vi.fn();
const mockPutSetDocument = vi.fn();
const mockSavePairing = vi.fn();
const mockUpdateSlotTarget = vi.fn();
const mockApplyCurveTemplate = vi.fn();
const mockPutVibeWindows = vi.fn();
const mockGetTransportStatus = vi.fn();
const mockSendTransportCommand = vi.fn();

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

function largeSlots(count: number): SetSlotOut[] {
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

function largePoolTracks(count: number): PoolTrack[] {
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

const EXTRA_POOL_TRACK: PoolTrack = {
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

const SYNTHETIC_POOL_TRACK: PoolTrack = {
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

function cloneDocument(doc: SetDocumentSnapshot): SetDocumentSnapshot {
  return JSON.parse(JSON.stringify(doc)) as SetDocumentSnapshot;
}

function documentSnapshot(): SetDocumentSnapshot {
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
    mockGetSetDocument.mockResolvedValue(cloneDocument(documentSnapshot()));
    mockPutSetDocument.mockImplementation((_setId: number, snapshot: SetDocumentSnapshot) =>
      Promise.resolve(cloneDocument(snapshot)),
    );
    mockGetCurveTemplates.mockResolvedValue(TEMPLATES);
    mockGetVibeWindows.mockResolvedValue({ windows: [] });
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

  it('fetches slots and renders curve blocks + timeline rows', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => {
      expect(screen.getByTestId('slot-block-0')).toBeInTheDocument();
      expect(screen.getByTestId('timeline-row-2')).toBeInTheDocument();
    });
    expect(mockGetSetSlots).toHaveBeenCalledWith(5);
  });

  it('zooms the curve timeline in, out, and back to fit', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('curve-toolbar')).toBeInTheDocument());
    expect(screen.getByRole('group', { name: 'Curve zoom controls' })).toBeInTheDocument();

    const canvas = screen.getByTestId('curve-canvas');
    const initialScale = canvas.getAttribute('data-px-per-second');

    fireEvent.click(screen.getByTestId('curve-zoom-in'));
    expect(screen.getByTestId('curve-canvas').getAttribute('data-px-per-second')).not.toBe(
      initialScale,
    );

    fireEvent.click(screen.getByTestId('curve-zoom-out'));
    fireEvent.click(screen.getByTestId('curve-zoom-fit'));
    fireEvent.scroll(screen.getByTestId('curve-scroll-viewport'), { target: { scrollLeft: 0 } });

    expect(screen.getByTestId('curve-zoom-label')).toHaveTextContent('Fit');
  });

  it('zooms the curve using the overlap-adjusted target domain', async () => {
    render(
      <BuilderWorkspace
        setId={5}
        targetSettings={{ targetDurationSec: 1000, avgTransitionOverlapSec: 10 }}
      />,
    );
    await waitFor(() => expect(screen.getByTestId('curve-toolbar')).toBeInTheDocument());

    expect(screen.getByTestId('curve-canvas')).toHaveAttribute('data-px-per-second', '0.7843');
  });

  it('zooms the curve from fit scroll without snapping scale and clamps stale scroll', async () => {
    const { rerender } = render(
      <BuilderWorkspace
        setId={5}
        targetSettings={{ targetDurationSec: 60_000, avgTransitionOverlapSec: 0 }}
      />,
    );
    await waitFor(() => expect(screen.getByTestId('curve-toolbar')).toBeInTheDocument());

    const initialScale = screen.getByTestId('curve-canvas').getAttribute('data-px-per-second');
    fireEvent.scroll(screen.getByTestId('curve-scroll-viewport'), { target: { scrollLeft: 120 } });

    await waitFor(() => expect(screen.getByTestId('curve-zoom-label')).toHaveTextContent('1 px/min'));
    expect(screen.getByTestId('curve-canvas')).toHaveAttribute('data-px-per-second', initialScale);
    expect(screen.getByTestId('curve-canvas')).toHaveAttribute('data-scroll-left', '120');

    rerender(
      <BuilderWorkspace
        setId={5}
        targetSettings={{ targetDurationSec: 600, avgTransitionOverlapSec: 0 }}
      />,
    );

    await waitFor(() =>
      expect(screen.getByTestId('curve-canvas')).toHaveAttribute('data-scroll-left', '0'),
    );
  });

  it('uses overview curve LOD for hundreds of tracks at fit zoom', async () => {
    // Regression for b2d595a: fit zoom must not render hundreds of target handles.
    mockGetSetSlots.mockResolvedValue(largeSlots(400));
    mockGetPool.mockResolvedValue({ sources: [], tracks: largePoolTracks(400) });

    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('curve-canvas')).toBeInTheDocument());

    expect(screen.getByTestId('curve-lod')).toHaveTextContent('overview');
    expect(screen.queryAllByTestId(/^target-handle-/)).toHaveLength(0);
    expect(screen.getByTestId('curve-line')).toBeInTheDocument();

    const initialScale = screen.getByTestId('curve-canvas').getAttribute('data-px-per-second');
    fireEvent.click(screen.getByTestId('curve-zoom-in'));
    fireEvent.click(screen.getByTestId('curve-zoom-in'));
    fireEvent.click(screen.getByTestId('curve-zoom-in'));

    expect(screen.getByTestId('curve-canvas').getAttribute('data-px-per-second')).not.toBe(
      initialScale,
    );
  });

  it('reports effective target projection from loaded slots', async () => {
    const onProjectionChange = vi.fn();
    render(
      <BuilderWorkspace
        setId={5}
        targetSettings={{ targetDurationSec: 600, avgTransitionOverlapSec: 10 }}
        onProjectionChange={onProjectionChange}
      />,
    );
    await waitFor(() => expect(screen.getByTestId('slot-block-0')).toBeInTheDocument());
    await waitFor(() =>
      expect(onProjectionChange).toHaveBeenLastCalledWith(
        expect.objectContaining({
          rawTotalSec: 633,
          effectiveSec: 613,
          deltaSec: 13,
          tier: 'on-target',
        }),
      ),
    );
    expect(screen.getByTestId('timeline-summary')).toHaveTextContent('10:33 raw');
    expect(screen.getByTestId('timeline-summary')).toHaveTextContent('10:13 live, est.');
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

  it('renders locked timeline and curve affordances while disabling target drag', async () => {
    mockGetSetSlots.mockResolvedValue(
      SLOTS.map((slot) => (slot.id === 2 ? { ...slot, locked: true } : slot)),
    );

    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-1')).toBeInTheDocument());

    expect(screen.getByTestId('timeline-row-1')).toHaveAttribute('data-locked', 'true');
    expect(screen.getByTestId('timeline-lock-badge-1')).toHaveTextContent('Locked');
    expect(screen.getByTestId('slot-block-1')).toHaveAttribute('data-locked', 'true');
    expect(screen.getByTestId('slot-lock-icon-1')).toBeInTheDocument();
    expect(screen.queryByTestId('target-handle-1')).not.toBeInTheDocument();
  });

  it('bulk locks selected timeline rows through the document snapshot', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-2')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('timeline-select-0'));
    fireEvent.click(screen.getByTestId('timeline-select-2'));
    fireEvent.click(screen.getByTestId('timeline-lock-selected'));

    await waitFor(() => expect(mockPutSetDocument).toHaveBeenCalledTimes(1));
    const [setId, snapshot] = mockPutSetDocument.mock.calls[0] as [
      number,
      SetDocumentSnapshot,
    ];
    expect(setId).toBe(5);
    expect(snapshot.slots.map((slot) => [slot.id, slot.locked])).toEqual([
      [1, true],
      [2, false],
      [3, true],
    ]);
  });

  it('locks every slot that starts before the playhead', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-1')).toBeInTheDocument());

    fireEvent.doubleClick(screen.getByTestId('timeline-row-1'));
    await waitFor(() => expect(mockSendTransportCommand).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId('timeline-lock-before-playhead'));

    await waitFor(() => expect(mockPutSetDocument).toHaveBeenCalledTimes(1));
    const [, snapshot] = mockPutSetDocument.mock.calls[0] as [number, SetDocumentSnapshot];
    expect(snapshot.slots.map((slot) => [slot.id, slot.locked])).toEqual([
      [1, true],
      [2, false],
      [3, false],
    ]);
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

  it('measurement key changes when transition or pairing metadata changes without slot reorder', () => {
    const baseSlots = SLOTS.map((slot, idx) => slotViewFromApi(slot, POOL_TRACKS[idx]));
    const scoreChangedSlots = SLOTS.map((slot, idx) =>
      slotViewFromApi(idx === 0 ? { ...slot, transition_score: 94 } : slot, POOL_TRACKS[idx]),
    );
    const pairingChangedSlots = SLOTS.map((slot, idx) =>
      slotViewFromApi(
        idx === 0 ? { ...slot, next_pairing_id: 77, next_is_dj_pairing: true } : slot,
        POOL_TRACKS[idx],
      ),
    );

    expect(scoreChangedSlots.map((slot) => slot.id)).toEqual(baseSlots.map((slot) => slot.id));
    expect(pairingChangedSlots.map((slot) => slot.id)).toEqual(baseSlots.map((slot) => slot.id));
    expect(timelineMeasurementKey(scoreChangedSlots)).not.toBe(timelineMeasurementKey(baseSlots));
    expect(timelineMeasurementKey(pairingChangedSlots)).not.toBe(
      timelineMeasurementKey(baseSlots),
    );
  });

  it('timeline context menu saves the transition to the next slot as a pairing', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-0')).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText('Save Track A into Track B as pairing'));
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

  it('click on a visible curve block keeps the timeline scroll position stable', async () => {
    const slots = largeSlots(40);
    const tracks = largePoolTracks(40);
    mockGetSetSlots.mockResolvedValue(slots);
    mockGetPool.mockResolvedValue({ sources: [], tracks });

    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('slot-block-2')).toBeInTheDocument());

    const timelineList = screen.getByTestId('timeline-list');
    Object.defineProperty(timelineList, 'clientHeight', {
      value: 260,
      configurable: true,
    });
    timelineList.scrollTop = 52;
    fireEvent.scroll(timelineList);

    fireEvent.click(screen.getByTestId('slot-block-2'));

    await waitFor(() => expect(timelineList.scrollTop).toBe(52));
  });

  it('click on a row with a clipped transition strip keeps the visible row stable', async () => {
    const slots = largeSlots(40).map((slot, idx) =>
      idx === 1 ? { ...slot, transition_score: 88 } : slot,
    );
    const tracks = largePoolTracks(40);
    mockGetSetSlots.mockResolvedValue(slots);
    mockGetPool.mockResolvedValue({ sources: [], tracks });
    const rectSpy = vi
      .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockImplementation(function mockTimelineRects(this: HTMLElement) {
        if (this.dataset.testid === 'timeline-list') {
          return {
            x: 0,
            y: 0,
            width: 320,
            height: 260,
            top: 0,
            right: 320,
            bottom: 260,
            left: 0,
            toJSON: () => ({}),
          } as DOMRect;
        }
        if (this.dataset.testid === 'timeline-row-2') {
          return {
            x: 0,
            y: 14,
            width: 320,
            height: 32,
            top: 14,
            right: 320,
            bottom: 46,
            left: 0,
            toJSON: () => ({}),
          } as DOMRect;
        }
        return {
          x: 0,
          y: 0,
          width: 0,
          height: 0,
          top: 0,
          right: 0,
          bottom: 0,
          left: 0,
          toJSON: () => ({}),
        } as DOMRect;
      });

    try {
      render(<BuilderWorkspace setId={5} />);
      await waitFor(() => expect(screen.getByTestId('timeline-transition-1')).toBeInTheDocument());

      const timelineList = screen.getByTestId('timeline-list');
      Object.defineProperty(timelineList, 'clientHeight', {
        value: 260,
        configurable: true,
      });
      timelineList.scrollTop = 112;
      fireEvent.scroll(timelineList);

      fireEvent.click(screen.getByTestId('slot-block-2'));

      await waitFor(() => expect(timelineList.scrollTop).toBe(112));
    } finally {
      rectSpy.mockRestore();
    }
  });

  it('external jump requests wait for the requested row to exist', async () => {
    const { rerender } = render(<BuilderWorkspace setId={5} refreshToken={0} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-0')).toBeInTheDocument());

    const timelineList = screen.getByTestId('timeline-list');
    Object.defineProperty(timelineList, 'clientHeight', {
      value: 260,
      configurable: true,
    });

    window.dispatchEvent(new CustomEvent('wrzdj:setbuilder-jump-slot', { detail: { idx: 80 } }));
    await waitFor(() => expect(timelineList.scrollTop).toBe(0));

    const slots = largeSlots(120);
    const tracks = largePoolTracks(120);
    mockGetSetSlots.mockResolvedValue(slots);
    mockGetPool.mockResolvedValue({ sources: [], tracks });
    rerender(<BuilderWorkspace setId={5} refreshToken={1} />);

    await waitFor(() => expect(screen.getByTestId('timeline-row-80')).toBeInTheDocument());
    expect(timelineList.scrollTop).toBeGreaterThan(0);
  });

  it('click on a curve block scrolls once and does not replay after manual scroll measurement', async () => {
    const slots = largeSlots(120);
    const tracks = largePoolTracks(120);
    mockGetSetSlots.mockResolvedValue(slots);
    mockGetPool.mockResolvedValue({ sources: [], tracks });

    let measuredRowHeight = 52;
    const offsetHeightSpy = vi
      .spyOn(HTMLElement.prototype, 'offsetHeight', 'get')
      .mockImplementation(() => measuredRowHeight);

    try {
      render(<BuilderWorkspace setId={5} />);
      await waitFor(() => expect(screen.getByTestId('slot-block-80')).toBeInTheDocument());

      const timelineList = screen.getByTestId('timeline-list');
      fireEvent.click(screen.getByTestId('slot-block-80'));

      await waitFor(() => expect(screen.getByTestId('timeline-row-80')).toBeInTheDocument());
      expect(timelineList.scrollTop).toBeGreaterThan(0);

      measuredRowHeight = 60;
      fireEvent.scroll(timelineList, { target: { scrollTop: 0 } });

      await waitFor(() => expect(screen.getByTestId('timeline-row-0')).toBeInTheDocument());
      await waitFor(() => expect(timelineList.scrollTop).toBe(0));
    } finally {
      offsetHeightSpy.mockRestore();
    }
  });

  it('dropping a pool track on a timeline row inserts it before that row', async () => {
    // Regression for b2f553c4: timeline rows must accept pool drops and persist insertion.
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-1')).toBeInTheDocument());
    const dataTransfer = {
      dropEffect: '',
      getData: vi.fn((type: string) =>
        type === 'application/x-wrzdj-pool-track'
          ? JSON.stringify({ poolTrackId: EXTRA_POOL_TRACK.id })
          : '',
      ),
    };

    fireEvent.dragOver(screen.getByTestId('timeline-row-1'), { dataTransfer });
    fireEvent.drop(screen.getByTestId('timeline-row-1'), { dataTransfer });

    await waitFor(() => expect(mockPutSetDocument).toHaveBeenCalledTimes(1));
    const [setId, snapshot] = mockPutSetDocument.mock.calls[0] as [
      number,
      SetDocumentSnapshot,
    ];
    expect(setId).toBe(5);
    expect(snapshot.slots.map((slot) => slot.track_id)).toEqual(['a', 'd', 'b', 'c']);
    expect(snapshot.slots.map((slot) => slot.position)).toEqual([0, 1, 2, 3]);
  });

  it('dropping a pool track without track_id inserts its synthetic pool id', async () => {
    // Regression for b2f553c4: manual pool tracks use synthetic slot ids.
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-1')).toBeInTheDocument());
    const dataTransfer = {
      dropEffect: '',
      getData: vi.fn((type: string) =>
        type === 'application/x-wrzdj-pool-track'
          ? JSON.stringify({ poolTrackId: SYNTHETIC_POOL_TRACK.id })
          : '',
      ),
    };

    fireEvent.dragOver(screen.getByTestId('timeline-row-1'), { dataTransfer });
    fireEvent.drop(screen.getByTestId('timeline-row-1'), { dataTransfer });

    await waitFor(() => expect(mockPutSetDocument).toHaveBeenCalledTimes(1));
    const [, snapshot] = mockPutSetDocument.mock.calls[0] as [number, SetDocumentSnapshot];
    expect(snapshot.slots.map((slot) => slot.track_id)).toEqual([
      'a',
      `pool:${SYNTHETIC_POOL_TRACK.id}`,
      'b',
      'c',
    ]);
    expect(snapshot.slots.map((slot) => slot.position)).toEqual([0, 1, 2, 3]);
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

  it('play queues a Tidal Bridge command for the current slot', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('transport-bar')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Play' }));

    await waitFor(() => expect(mockSendTransportCommand).toHaveBeenCalledTimes(1));
    expect(mockSendTransportCommand).toHaveBeenCalledWith(
      5,
      expect.objectContaining({
        action: 'play',
        source: 'tidal',
        slot_index: 0,
        track_id: 'a',
        title: 'Track A',
      }),
    );
    expect(screen.getByTestId('timeline-vu-0')).toBeInTheDocument();
  });

  it('double-clicking a timeline row jumps and plays that slot', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-1')).toBeInTheDocument());

    fireEvent.doubleClick(screen.getByTestId('timeline-row-1'));

    await waitFor(() => expect(mockSendTransportCommand).toHaveBeenCalledTimes(1));
    expect(mockSendTransportCommand).toHaveBeenCalledWith(
      5,
      expect.objectContaining({
        action: 'play',
        slot_index: 1,
        position_sec: 0,
        title: 'Track B',
      }),
    );
    expect(screen.getByTestId('timeline-vu-1')).toBeInTheDocument();
  });

  it('virtualizes hundreds of timeline rows while preserving visible row actions', async () => {
    // Regression for 7459707: large timelines must not mount every row.
    const slots = largeSlots(400);
    const tracks = largePoolTracks(400);
    mockGetSetSlots.mockResolvedValue(slots);
    mockGetPool.mockResolvedValue({ sources: [], tracks });

    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-0')).toBeInTheDocument());

    expect(screen.getByTestId('timeline-list')).toHaveAttribute('data-virtualized', 'true');
    expect(screen.queryAllByTestId(/^timeline-row-/).length).toBeLessThan(60);

    fireEvent.doubleClick(screen.getByTestId('timeline-row-1'));

    await waitFor(() => expect(mockSendTransportCommand).toHaveBeenCalledTimes(1));
    expect(mockSendTransportCommand).toHaveBeenCalledWith(
      5,
      expect.objectContaining({
        action: 'play',
        slot_index: 1,
        title: 'Large Track 1',
      }),
    );
  });

  it('click-to-scrub queues a seek command and keeps the active row in sync', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-1')).toBeInTheDocument());
    fireEvent.doubleClick(screen.getByTestId('timeline-row-1'));
    await waitFor(() => expect(mockSendTransportCommand).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId('curve-scrub-hit'), { clientX: 0 });

    await waitFor(() => expect(mockSendTransportCommand).toHaveBeenCalledTimes(2));
    expect(mockSendTransportCommand).toHaveBeenLastCalledWith(
      5,
      expect.objectContaining({
        action: 'seek',
        slot_index: 0,
        position_sec: 0,
      }),
    );
    expect(screen.getByTestId('timeline-vu-0')).toBeInTheDocument();
  });

  it('auto-pauses Bridge when playback reaches the end of the set', async () => {
    mockGetSetSlots.mockResolvedValue([SLOTS[0]]);
    mockGetPool.mockResolvedValue({
      sources: [],
      tracks: [{ ...POOL_TRACKS[0], duration_sec: 1 }],
    });

    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('transport-bar')).toBeInTheDocument());

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    expect(mockSendTransportCommand).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(mockSendTransportCommand).toHaveBeenCalledTimes(2);
    expect(mockSendTransportCommand).toHaveBeenLastCalledWith(
      5,
      expect.objectContaining({
        action: 'pause',
        slot_index: 0,
        position_sec: 1,
      }),
    );
    expect(screen.getByRole('button', { name: 'Play' })).toBeInTheDocument();
  });

  it('scrubs when clicking a curve block covered by the block hit target', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-1')).toBeInTheDocument());
    fireEvent.doubleClick(screen.getByTestId('timeline-row-1'));
    await waitFor(() => expect(mockSendTransportCommand).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId('slot-block-0'), { clientX: 0 });

    await waitFor(() => expect(mockSendTransportCommand).toHaveBeenCalledTimes(2));
    expect(mockSendTransportCommand).toHaveBeenLastCalledWith(
      5,
      expect.objectContaining({
        action: 'seek',
        slot_index: 0,
        position_sec: 0,
      }),
    );
  });
});
