import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import TimelineRow from '../TimelineRow';
import type { SlotView } from '../types';
import { readSlotReorderDragPayload } from '../dnd';

function slot(id: number, locked = false): SlotView {
  return {
    id, position: id, locked, targetEnergy: null, transitionScore: 50,
    nextPairingId: null, nextIsDjPairing: false,
    track: { id: `t${id}`, title: `T${id}`, artist: `A${id}`, durationSec: 210, energy: 5, bpm: 120, key: '8A' },
  };
}

function renderRow(s: SlotView) {
  const slots = [s];
  return render(
    <TimelineRow
      slot={s} prevSlot={null} nextSlot={null} idx={0} slots={slots}
      hoveredIdx={null} currentIdx={-1} positionSec={0} playing={false}
      selected={false} dropIdx={null} setDropIdx={vi.fn()} onHover={vi.fn()}
      onSelectedChange={vi.fn()} setMenu={vi.fn()}
    />,
  );
}

function fakeDataTransfer(): DataTransfer {
  const store: Record<string, string> = {};
  return {
    effectAllowed: 'none',
    setData: (t: string, v: string) => { store[t] = v; },
    getData: (t: string) => store[t] ?? '',
  } as unknown as DataTransfer;
}

describe('TimelineRow drag source', () => {
  it('is draggable when the slot is unlocked', () => {
    renderRow(slot(1, false));
    expect(screen.getByTestId('timeline-row-0').getAttribute('draggable')).toBe('true');
  });

  it('is not draggable when the slot is locked', () => {
    renderRow(slot(1, true));
    expect(screen.getByTestId('timeline-row-0').getAttribute('draggable')).toBe('false');
  });

  it('writes the slot id on drag start', () => {
    renderRow(slot(7, false));
    const dt = fakeDataTransfer();
    fireEvent.dragStart(screen.getByTestId('timeline-row-0'), { dataTransfer: dt });
    expect(readSlotReorderDragPayload(dt)).toEqual({ slotId: 7 });
  });
});

function renderRowAt(slots: SlotView[], idx: number, onMoveSlot = vi.fn()) {
  render(
    <TimelineRow
      slot={slots[idx]} prevSlot={idx > 0 ? slots[idx - 1] : null}
      nextSlot={idx < slots.length - 1 ? slots[idx + 1] : null}
      idx={idx} slots={slots}
      hoveredIdx={null} currentIdx={-1} positionSec={0} playing={false}
      selected={false} dropIdx={null} setDropIdx={vi.fn()} onHover={vi.fn()}
      onSelectedChange={vi.fn()} setMenu={vi.fn()} onMoveSlot={onMoveSlot}
    />,
  );
  return onMoveSlot;
}

describe('TimelineRow move controls', () => {
  it('renders up/down controls for an unlocked slot', () => {
    renderRowAt([slot(1), slot(2), slot(3)], 1);
    expect(screen.getByTestId('timeline-move-up-1')).toBeTruthy();
    expect(screen.getByTestId('timeline-move-down-1')).toBeTruthy();
  });

  it('renders no move controls for a locked slot', () => {
    renderRowAt([slot(1), slot(2, true), slot(3)], 1);
    expect(screen.queryByTestId('timeline-move-up-1')).toBeNull();
    expect(screen.queryByTestId('timeline-move-down-1')).toBeNull();
  });

  it('disables up on the first slot and down on the last slot', () => {
    renderRowAt([slot(1), slot(2), slot(3)], 0);
    expect(screen.getByTestId('timeline-move-up-0').hasAttribute('disabled')).toBe(true);
    expect(screen.getByTestId('timeline-move-down-0').hasAttribute('disabled')).toBe(false);
  });

  it('calls onMoveSlot with the slot id and direction on click', () => {
    const onMoveSlot = renderRowAt([slot(1), slot(2), slot(3)], 1);
    fireEvent.click(screen.getByTestId('timeline-move-down-1'));
    expect(onMoveSlot).toHaveBeenCalledWith(2, 'down');
  });

  it('disables a move that would displace a locked slot', () => {
    renderRowAt([slot(1), slot(2, true), slot(3)], 2); // slot 3; moving up crosses the lock
    expect(screen.getByTestId('timeline-move-up-2').hasAttribute('disabled')).toBe(true);
  });
});
