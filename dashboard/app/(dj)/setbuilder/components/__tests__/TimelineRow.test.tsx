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
