import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { EXTRA_POOL_TRACK, SLOTS, largePoolTracks, largeSlots, mockApplyCurveTemplate, mockGetPool, mockGetSetSlots, mockPutSetDocument, mockSendTransportCommand, mockUpdateSlotTarget } from './BuilderWorkspaceTestSupport';
import BuilderWorkspace from '../components/BuilderWorkspace';
import type { SetDocumentSnapshot } from '@/lib/api/types';

describe('BuilderWorkspace', () => {


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

  it('replaces the selected slot through the saved set document', async () => {
    mockGetPool.mockResolvedValue({ sources: [], tracks: [EXTRA_POOL_TRACK] });
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('target-handle-0')).toBeInTheDocument());

    fireEvent.pointerDown(screen.getByTestId('target-handle-0'), { clientY: 50 });
    fireEvent.pointerMove(window, { clientY: -100 });
    fireEvent.pointerUp(window);
    fireEvent.click(await screen.findByTestId('replace-candidate-d'));

    await waitFor(() => expect(mockPutSetDocument).toHaveBeenCalledTimes(1));
    const [setId, snapshot] = mockPutSetDocument.mock.calls[0] as [number, SetDocumentSnapshot];
    expect(setId).toBe(5);
    expect(snapshot.slots[0]).toMatchObject({ id: 1, track_id: 'd' });
    expect(snapshot.slots[0].target_energy).toBeNull();
    await waitFor(() => expect(screen.getByTestId('timeline-row-0')).toBeInTheDocument());
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
});
