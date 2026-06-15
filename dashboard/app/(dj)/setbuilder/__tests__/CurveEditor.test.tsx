import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll } from 'vitest';
import CurveEditor from '../components/CurveEditor';
import type { SlotView, VibeWindowView } from '../components/types';

beforeAll(() => {
  // jsdom has no ResizeObserver
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

function mkSlot(
  idx: number,
  over: Partial<SlotView['track']> = {},
  target: number | null = null,
): SlotView {
  return {
    id: idx + 1,
    position: idx,
    locked: false,
    targetEnergy: target,
    transitionScore: null,
    nextPairingId: null,
    nextIsDjPairing: false,
    track: {
      id: `t${idx}`,
      title: `Track ${idx}`,
      artist: 'Artist',
      durationSec: 200,
      energy: 5,
      bpm: 120,
      key: '8A',
      ...over,
    },
  };
}

const noWindows: VibeWindowView[] = [];

function renderEditor(overrides: Partial<React.ComponentProps<typeof CurveEditor>> = {}) {
  const props: React.ComponentProps<typeof CurveEditor> = {
    slots: [mkSlot(0), mkSlot(1), mkSlot(2)],
    view: 'normal',
    windows: noWindows,
    hoveredIdx: null,
    onHover: vi.fn(),
    ...overrides,
  };
  return { ...render(<CurveEditor {...props} />), props };
}

describe('CurveEditor', () => {
  it('shows the empty state without slots', () => {
    renderEditor({ slots: [] });
    expect(screen.getByTestId('curve-empty')).toBeInTheDocument();
  });

  it('renders one block per slot and the derived curve line', () => {
    renderEditor();
    expect(screen.getByTestId('slot-block-0')).toBeInTheDocument();
    expect(screen.getByTestId('slot-block-2')).toBeInTheDocument();
    expect(screen.getByTestId('curve-line')).toBeInTheDocument();
  });

  it('renders a purple seam pin for saved DJ pairings', () => {
    const paired = mkSlot(0);
    paired.nextPairingId = 42;
    paired.nextIsDjPairing = true;
    renderEditor({ slots: [paired, mkSlot(1)] });
    expect(screen.getByTestId('pairing-pin-0')).toBeInTheDocument();
  });

  it('renders target marker and amber over-region using overlap-adjusted raw target', () => {
    const slots = [
      mkSlot(0, { durationSec: 400 }),
      mkSlot(1, { durationSec: 300 }),
      mkSlot(2, { durationSec: 300 }),
    ];
    const { rerender, props } = renderEditor({
      slots,
      targetDurationSec: 500,
      avgTransitionOverlapSec: 0,
    });

    const marker = screen.getByTestId('curve-target-marker');
    expect(marker).toHaveAttribute('x1', '400');
    expect(screen.getByTestId('curve-over-region')).toBeInTheDocument();

    rerender(
      <CurveEditor
        {...props}
        targetDurationSec={500}
        avgTransitionOverlapSec={30}
      />,
    );
    expect(screen.getByTestId('curve-target-marker')).toHaveAttribute('x1', '448');
  });

  it('maps playhead and scrub positions against the extended target domain', () => {
    const onScrub = vi.fn();
    const { container } = renderEditor({
      slots: [
        mkSlot(0, { durationSec: 200 }),
        mkSlot(1, { durationSec: 200 }),
        mkSlot(2, { durationSec: 200 }),
      ],
      targetDurationSec: 900,
      avgTransitionOverlapSec: 0,
      playheadSec: 300,
      scrubEnabled: true,
      onScrub,
    });

    const playheadLine = screen.getByTestId('curve-playhead').querySelector('line');
    expect(Number(playheadLine?.getAttribute('x1'))).toBeCloseTo(266.67);

    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    vi.spyOn(svg as SVGSVGElement, 'getBoundingClientRect').mockReturnValue({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 800,
      bottom: 160,
      width: 800,
      height: 160,
      toJSON: () => ({}),
    } as DOMRect);

    fireEvent.click(screen.getByTestId('curve-scrub-hit'), { clientX: 400 });
    expect(onScrub).toHaveBeenLastCalledWith(450);

    fireEvent.click(screen.getByTestId('curve-scrub-hit'), { clientX: 800 });
    expect(onScrub).toHaveBeenLastCalledWith(600);
  });

  it('renders amber hatch when target > energy and dashed line when target < energy', () => {
    renderEditor({
      slots: [
        mkSlot(0, { energy: 4 }, 8), // target above
        mkSlot(1, { energy: 8 }, 4), // target below
        mkSlot(2, { energy: 5 }, null), // on-load target = track energy → no mismatch
      ],
    });
    expect(screen.getByTestId('mismatch-above-0')).toBeInTheDocument();
    expect(screen.getByTestId('mismatch-below-1')).toBeInTheDocument();
    expect(screen.queryByTestId('mismatch-above-2')).not.toBeInTheDocument();
    expect(screen.queryByTestId('mismatch-below-2')).not.toBeInTheDocument();
  });

  it('renders no seams in normal view, tier-colored seams in bpm view', () => {
    const slots = [
      mkSlot(0, { bpm: 100 }),
      mkSlot(1, { bpm: 101 }), // 1% → match (green)
      mkSlot(2, { bpm: 120 }), // 15.8% → clash (red)
    ];
    const { rerender, props } = renderEditor({ slots });
    expect(screen.queryByTestId('seam-band-0')).not.toBeInTheDocument();

    rerender(<CurveEditor {...props} view="bpm" />);
    expect(screen.getByTestId('seam-band-0').dataset.stroke).toBe('#22c55e');
    expect(screen.getByTestId('seam-band-1').dataset.stroke).toBe('#ef4444');
  });

  it('renders key-view seams from camelot tiers', () => {
    const slots = [
      mkSlot(0, { key: '8A' }),
      mkSlot(1, { key: '9A' }), // adjacent → perfect (green)
      mkSlot(2, { key: '3A' }), // far → clash (red)
    ];
    renderEditor({ slots, view: 'key' });
    expect(screen.getByTestId('seam-band-0').dataset.stroke).toBe('#22c55e');
    expect(screen.getByTestId('seam-band-1').dataset.stroke).toBe('#ef4444');
  });

  it('shows the exact-metric chip on hovered seam (bpm %)', () => {
    const slots = [mkSlot(0, { bpm: 100 }), mkSlot(1, { bpm: 104 })];
    renderEditor({ slots, view: 'bpm', hoveredIdx: 0 });
    expect(screen.getByTestId('seam-chip-0')).toHaveTextContent('3.8%');
  });

  it('emits hover + click for timeline sync', () => {
    const onHover = vi.fn();
    const onBlockClick = vi.fn();
    renderEditor({ onHover, onBlockClick });
    fireEvent.mouseEnter(screen.getByTestId('slot-block-1'));
    expect(onHover).toHaveBeenCalledWith(1);
    fireEvent.click(screen.getByTestId('slot-block-1'));
    expect(onBlockClick).toHaveBeenCalledWith(1);
    fireEvent.mouseLeave(screen.getByTestId('slot-block-1'));
    expect(onHover).toHaveBeenCalledWith(null);
  });

  it('drag on a handle shows the live chip and fires onTargetDragEnd on release', () => {
    const onTargetDragEnd = vi.fn();
    renderEditor({ onTargetDragEnd });
    const handle = screen.getByTestId('target-handle-1');
    fireEvent.pointerDown(handle, { clientY: 100 });
    expect(screen.getByTestId('drag-chip')).toBeInTheDocument();
    fireEvent.pointerMove(window, { clientY: 0 });
    fireEvent.pointerUp(window);
    expect(onTargetDragEnd).toHaveBeenCalledTimes(1);
    const [idx, energy] = onTargetDragEnd.mock.calls[0];
    expect(idx).toBe(1);
    expect(typeof energy).toBe('number');
  });

  it('renders vibe windows with label and supports right-click delete', () => {
    const onWindowDelete = vi.fn();
    renderEditor({
      windows: [{ id: 'w1', t0: 0.2, t1: 0.4, label: 'First Dance' }],
      onWindowDelete,
      onWindowChange: vi.fn(),
    });
    expect(screen.getByTestId('vibe-window-w1')).toHaveTextContent('FIRST DANCE');
    fireEvent.contextMenu(screen.getByTestId('vibe-window-header-w1'));
    expect(onWindowDelete).toHaveBeenCalledWith('w1');
  });

  it('renders only viewport-visible slot blocks in detail zoom', () => {
    // Regression for b2d595a: large sets must not render every SVG slot node at once.
    const slots = Array.from({ length: 200 }, (_, i) => mkSlot(i, { durationSec: 60 }));
    renderEditor({
      slots,
      pxPerSecond: 2,
      scrollLeft: 60 * 50 * 2,
      viewportWidth: 600,
    });

    expect(screen.queryByTestId('slot-block-0')).not.toBeInTheDocument();
    expect(screen.getByTestId('slot-block-50')).toBeInTheDocument();
    expect(document.querySelectorAll('[data-testid^="slot-block-"]').length).toBeLessThan(30);
  });

  it('hides per-slot drag handles at overview zoom', () => {
    // Regression for b2d595a: overview mode should not expose hundreds of tiny handles.
    const slots = Array.from({ length: 200 }, (_, i) => mkSlot(i, { durationSec: 60 }));
    renderEditor({
      slots,
      pxPerSecond: 0.02,
      scrollLeft: 0,
      viewportWidth: 600,
    });

    expect(screen.getByTestId('curve-lod')).toHaveTextContent('overview');
    expect(screen.queryByTestId('target-handle-0')).not.toBeInTheDocument();
    expect(screen.queryByTestId('slot-block-0')).not.toBeInTheDocument();
    expect(screen.getByTestId('curve-line')).toBeInTheDocument();
  });
});
