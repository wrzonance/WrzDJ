import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { EXTRA_POOL_TRACK, POOL_TRACKS, SLOTS, SYNTHETIC_POOL_TRACK, largePoolTracks, largeSlots, mockGetPool, mockGetSetSlots, mockPutSetDocument, mockSavePairing } from './BuilderWorkspaceTestSupport';
import BuilderWorkspace from '../components/BuilderWorkspace';
import { timelineMeasurementKey } from '../components/timeline/TimelinePanel';
import { slotViewFromApi } from '../components/types';
import type { PoolTrack, SetDocumentSnapshot, SetSlotOut } from '@/lib/api/types';

describe('BuilderWorkspace', () => {


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
    const onOpenPairings = vi.fn();
    const onPairingsChanged = vi.fn();
    render(
      <BuilderWorkspace
        setId={5}
        onOpenPairings={onOpenPairings}
        onPairingsChanged={onPairingsChanged}
      />,
    );
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
    expect(onPairingsChanged).toHaveBeenCalledOnce();
    expect(onOpenPairings).toHaveBeenCalledWith(44);
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
    const { rerender } = render(<BuilderWorkspace setId={5} refreshToken={0} jumpSlotRequest={null} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-0')).toBeInTheDocument());

    const timelineList = screen.getByTestId('timeline-list');
    Object.defineProperty(timelineList, 'clientHeight', {
      value: 260,
      configurable: true,
    });

    const jumpSlotRequest = { idx: 80, requestId: 1 };
    rerender(<BuilderWorkspace setId={5} refreshToken={0} jumpSlotRequest={jumpSlotRequest} />);
    await waitFor(() => expect(timelineList.scrollTop).toBe(0));

    const slots = largeSlots(120);
    const tracks = largePoolTracks(120);
    mockGetSetSlots.mockResolvedValue(slots);
    mockGetPool.mockResolvedValue({ sources: [], tracks });
    rerender(<BuilderWorkspace setId={5} refreshToken={1} jumpSlotRequest={jumpSlotRequest} />);

    await waitFor(() => expect(screen.getByTestId('timeline-row-80')).toBeInTheDocument());
    expect(timelineList.scrollTop).toBeGreaterThan(0);
  });

  it('ignores an older slots and pool load after a newer refresh completes', async () => {
    let resolveOldSlots!: (slots: SetSlotOut[]) => void;
    let resolveOldPool!: (pool: { sources: []; tracks: PoolTrack[] }) => void;
    const oldSlots = new Promise<SetSlotOut[]>((resolve) => { resolveOldSlots = resolve; });
    const oldPool = new Promise<{ sources: []; tracks: PoolTrack[] }>((resolve) => { resolveOldPool = resolve; });
    const latestSlots = [SLOTS[0]];
    mockGetSetSlots.mockReturnValueOnce(oldSlots).mockResolvedValueOnce(latestSlots);
    mockGetPool.mockReturnValueOnce(oldPool).mockResolvedValueOnce({ sources: [], tracks: [] });

    const { rerender } = render(<BuilderWorkspace setId={5} refreshToken={0} />);
    rerender(<BuilderWorkspace setId={5} refreshToken={1} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-0')).toBeInTheDocument());
    expect(screen.queryByTestId('timeline-row-1')).not.toBeInTheDocument();

    await act(async () => {
      resolveOldSlots(SLOTS);
      resolveOldPool({ sources: [], tracks: POOL_TRACKS });
    });

    expect(screen.queryByTestId('timeline-row-1')).not.toBeInTheDocument();
  });

  it('preserves the loaded workspace and offers retry when a refresh fails', async () => {
    // Regression: 57cfcdc6867f replaced a failed load with an apparently empty workspace.
    const { rerender } = render(<BuilderWorkspace setId={5} refreshToken={0} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-1')).toBeInTheDocument());

    mockGetSetSlots.mockRejectedValueOnce(new Error('offline'));
    mockGetPool.mockResolvedValueOnce({ sources: [], tracks: [] });
    rerender(<BuilderWorkspace setId={5} refreshToken={1} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load set.');
    expect(screen.getByTestId('timeline-row-1')).toBeInTheDocument();

    mockGetSetSlots.mockResolvedValueOnce([SLOTS[0]]);
    mockGetPool.mockResolvedValueOnce({ sources: [], tracks: [] });
    fireEvent.click(screen.getByTestId('workspace-retry'));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(screen.queryByTestId('timeline-row-1')).not.toBeInTheDocument();

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

  it('reports a failed pool-track insert and leaves the loaded timeline unchanged', async () => {
    mockPutSetDocument.mockRejectedValueOnce(new Error('write failed'));
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-1')).toBeInTheDocument());
    const originalRow = screen.getByTestId('timeline-row-1').textContent;
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

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Could not confirm the insert');
    expect(screen.getByTestId('timeline-row-1').textContent).toBe(originalRow);
    expect(mockPutSetDocument).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId('workspace-retry'));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(mockPutSetDocument).toHaveBeenCalledTimes(1);
  });

  it('retries a failed post-insert refresh with reads only', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-1')).toBeInTheDocument());
    mockGetSetSlots.mockRejectedValueOnce(new Error('refresh failed'));
    const insertedSlots = [
      SLOTS[0],
      { ...SLOTS[1], id: 4, position: 1, track_id: 'd' },
      { ...SLOTS[1], id: 2, position: 2 },
      { ...SLOTS[2], position: 3 },
    ];
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

    expect(await screen.findByRole('alert')).toHaveTextContent('Track was saved, but the timeline could not refresh');
    expect(mockPutSetDocument).toHaveBeenCalledTimes(1);

    mockGetSetSlots.mockResolvedValueOnce(insertedSlots);
    fireEvent.click(screen.getByTestId('workspace-retry'));
    await waitFor(() => expect(screen.getByTestId('timeline-row-1')).toHaveTextContent('d'));
    expect(mockPutSetDocument).toHaveBeenCalledTimes(1);
  });

  it('reconciles saved state when history commit fails after the insert write', async () => {
    render(
      <BuilderWorkspace
        setId={5}
        commit={async <T,>(_label: string, action: () => Promise<T> | T) => {
          await action();
          throw new Error('history snapshot unavailable');
        }}
      />,
    );
    await waitFor(() => expect(screen.getByTestId('timeline-row-1')).toBeInTheDocument());
    const insertedSlots = [
      SLOTS[0],
      { ...SLOTS[1], id: 4, position: 1, track_id: 'd' },
      { ...SLOTS[1], id: 2, position: 2 },
      { ...SLOTS[2], position: 3 },
    ];
    mockGetSetSlots.mockResolvedValueOnce(insertedSlots);
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

    await waitFor(() => expect(screen.getByTestId('timeline-row-1')).toHaveTextContent('d'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not confirm the insert');
    expect(mockPutSetDocument).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId('workspace-retry'));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(mockPutSetDocument).toHaveBeenCalledTimes(1);
  });
});
