import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import ReplacePopover from '../components/ReplacePopover';
import { rankReplacementCandidates } from '../components/curveMath';
import type { SlotView, TrackView } from '../components/types';

function mkTrack(over: Partial<TrackView> = {}): TrackView {
  return {
    id: 'cur',
    title: 'Current Song',
    artist: 'Artist',
    durationSec: 200,
    energy: 5,
    bpm: 120,
    key: '8A',
    ...over,
  };
}

const slot: SlotView = {
  id: 11,
  position: 0,
  locked: false,
  targetEnergy: 8,
  transitionScore: null,
  nextPairingId: null,
  nextIsDjPairing: false,
  track: mkTrack(),
};

const prompt = { slotIdx: 0, targetEnergy: 8, anchorX: 100, anchorY: 100 };

describe('ReplacePopover', () => {
  it('renders ranked candidates and fires onReplace with slot + track ids', () => {
    const pool = [
      mkTrack({ id: 'a', title: 'Fit A', energy: 8, bpm: 121, key: '8A' }),
      mkTrack({ id: 'b', title: 'Fit B', energy: 7.6, bpm: 122, key: '9A' }),
    ];
    const candidates = rankReplacementCandidates(8, null, pool, new Set());
    const onReplace = vi.fn();
    render(
      <ReplacePopover
        prompt={prompt}
        slot={slot}
        candidates={candidates}
        onReplace={onReplace}
        onKeep={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByTestId('replace-popover')).toBeInTheDocument();
    expect(screen.getByText('Fit A')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('replace-candidate-a'));
    expect(onReplace).toHaveBeenCalledWith(11, 'a');
  });

  it('shows locked-slot state and skips replacement actions', () => {
    const lockedSlot = { ...slot, locked: true };
    const candidates = rankReplacementCandidates(
      8,
      null,
      [mkTrack({ id: 'a', title: 'Fit A', energy: 8, bpm: 121, key: '8A' })],
      new Set(),
    );
    const onReplace = vi.fn();
    render(
      <ReplacePopover
        prompt={prompt}
        slot={lockedSlot}
        candidates={candidates}
        onReplace={onReplace}
        onKeep={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );

    expect(screen.getByTestId('replace-locked')).toHaveTextContent(
      'Skipped because this slot is locked',
    );
    fireEvent.click(screen.getByTestId('replace-candidate-a'));
    expect(onReplace).not.toHaveBeenCalled();
  });

  it('shows the empty state when no candidates fit', () => {
    render(
      <ReplacePopover
        prompt={prompt}
        slot={slot}
        candidates={[]}
        onReplace={vi.fn()}
        onKeep={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByTestId('replace-empty')).toBeInTheDocument();
  });

  it('keep + dismiss callbacks', () => {
    const onKeep = vi.fn();
    const onDismiss = vi.fn();
    render(
      <ReplacePopover
        prompt={prompt}
        slot={slot}
        candidates={[]}
        onReplace={vi.fn()}
        onKeep={onKeep}
        onDismiss={onDismiss}
      />,
    );
    fireEvent.click(screen.getByTestId('replace-keep'));
    expect(onKeep).toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('replace-backdrop'));
    expect(onDismiss).toHaveBeenCalled();
  });
});
