import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, createEvent } from '@testing-library/react';
import TimelinePanel from '../TimelinePanel';
import type { SlotView } from '../types';
import { writeSlotReorderDragPayload } from '../dnd';

const ROW_HEIGHT = 52;

// Give the virtualized list deterministic, non-zero geometry. Under jsdom the
// real hook sees a zero-height viewport, so totalHeight collapses to 0 and the
// pointer->index mapping can never be exercised. This mock renders every row
// and maps pointerTop straight to an index, so clientY drives insertIdx.
vi.mock('../useMeasuredVirtualList', () => ({
  useMeasuredVirtualList: ({ itemCount }: { itemCount: number }) => ({
    startIdx: 0,
    endIdx: itemCount,
    beforeHeight: 0,
    afterHeight: 0,
    totalHeight: itemCount * ROW_HEIGHT,
    items: Array.from({ length: itemCount }, (_, idx) => ({
      idx,
      key: idx,
      top: idx * ROW_HEIGHT,
      height: ROW_HEIGHT,
    })),
    setMeasuredHeight: vi.fn(),
    scrollTopForIndex: (idx: number) => idx * ROW_HEIGHT,
    indexFromScrollTop: (top: number) =>
      Math.max(0, Math.min(itemCount, Math.floor(top / ROW_HEIGHT))),
  }),
}));

function slot(id: number, locked = false): SlotView {
  return {
    id, position: id, locked, targetEnergy: null, transitionScore: 50,
    nextPairingId: null, nextIsDjPairing: false,
    track: { id: `t${id}`, title: `T${id}`, artist: `A${id}`, durationSec: 210, energy: 5, bpm: 120, key: '8A' },
  };
}

function reorderDataTransfer(slotId: number): DataTransfer {
  const store: Record<string, string> = {};
  const dt = {
    effectAllowed: 'none', dropEffect: 'none',
    setData: (t: string, v: string) => { store[t] = v; },
    getData: (t: string) => store[t] ?? '',
    get types() { return Object.keys(store); },
  } as unknown as DataTransfer;
  writeSlotReorderDragPayload(dt, slotId);
  return dt;
}

// jsdom's DragEvent constructor drops the clientY from the init dict, so a plain
// fireEvent.drop({ clientY }) arrives with clientY === undefined. Build the event
// and force the coordinate on before dispatch so the pointer->index path runs.
function fireReorderDrop(el: Element, dataTransfer: DataTransfer, clientY: number) {
  const event = createEvent.drop(el, { dataTransfer });
  Object.defineProperty(event, 'clientY', { value: clientY });
  fireEvent(el, event);
}

function fireReorderDragOver(el: Element, dataTransfer: DataTransfer, clientY: number) {
  const event = createEvent.dragOver(el, { dataTransfer });
  Object.defineProperty(event, 'clientY', { value: clientY });
  fireEvent(el, event);
}

function renderPanel(slots: SlotView[], onSlotReorder = vi.fn()) {
  render(
    <TimelinePanel
      slots={slots} hoveredIdx={null} currentIdx={-1} positionSec={0}
      playing={false} onHover={vi.fn()} scrollRequest={null}
      onSlotReorder={onSlotReorder}
    />,
  );
  return onSlotReorder;
}

describe('TimelinePanel reorder drop', () => {
  it('calls onSlotReorder with the source slot id and resolved target index', () => {
    const slots = [slot(1), slot(2), slot(3)];
    const onSlotReorder = renderPanel(slots);
    const dt = reorderDataTransfer(1);
    const list = screen.getByTestId('timeline-list');
    // clientY 60 -> pointerTop 60 -> floor(60/52) = insertIdx 1.
    fireEvent.dragStart(screen.getByTestId('timeline-row-0'), { dataTransfer: dt });
    fireReorderDrop(list, dt, 60);
    expect(onSlotReorder).toHaveBeenCalledTimes(1);
    expect(onSlotReorder).toHaveBeenCalledWith(1, 1);
  });

  it('reorders within a span that does not cross a locked slot', () => {
    const slots = [slot(1), slot(2), slot(3, true)];
    const onSlotReorder = renderPanel(slots);
    const dt = reorderDataTransfer(1);
    const list = screen.getByTestId('timeline-list');
    // Drag idx 0 to insertIdx 1; the locked slot at idx 2 is outside the [0,1] span.
    fireEvent.dragStart(screen.getByTestId('timeline-row-0'), { dataTransfer: dt });
    fireReorderDrop(list, dt, 60);
    expect(onSlotReorder).toHaveBeenCalledTimes(1);
    expect(onSlotReorder).toHaveBeenCalledWith(1, 1);
  });

  it('does not reorder across a locked slot', () => {
    const slots = [slot(1), slot(2, true), slot(3)];
    const onSlotReorder = renderPanel(slots);
    const dt = reorderDataTransfer(1);
    const list = screen.getByTestId('timeline-list');
    // Drag idx 0 to the end; the locked slot at idx 1 sits inside the span.
    fireEvent.dragStart(screen.getByTestId('timeline-row-0'), { dataTransfer: dt });
    fireReorderDrop(list, dt, 999);
    expect(onSlotReorder).not.toHaveBeenCalled();
  });

  it('reorders when the drop lands on a row (bubbles past the row pool handler)', () => {
    const slots = [slot(1), slot(2), slot(3)];
    const onSlotReorder = renderPanel(slots);
    const dt = reorderDataTransfer(1);
    // Drop ON a row, not the list root — this is where real drops land. The
    // row must let the reorder drag bubble to the list's reorder handler.
    fireEvent.dragStart(screen.getByTestId('timeline-row-0'), { dataTransfer: dt });
    fireReorderDrop(screen.getByTestId('timeline-row-2'), dt, 999);
    expect(onSlotReorder).toHaveBeenCalledTimes(1);
    expect(onSlotReorder).toHaveBeenCalledWith(1, 3);
  });

  it('reports a move dropEffect for a reorder dragover bubbled from a row', () => {
    const slots = [slot(1), slot(2), slot(3)];
    renderPanel(slots);
    const dt = reorderDataTransfer(1);
    fireEvent.dragStart(screen.getByTestId('timeline-row-0'), { dataTransfer: dt });
    fireReorderDragOver(screen.getByTestId('timeline-row-1'), dt, 60);
    expect(dt.dropEffect).toBe('move');
  });
});
