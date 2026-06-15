import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import TargetEditor from '../components/TargetEditor';
import { projectTarget } from '../components/targetMath';
import type { SlotView } from '../components/types';

const slots: SlotView[] = [
  {
    id: 1,
    position: 0,
    locked: false,
    targetEnergy: null,
    transitionScore: null,
    nextPairingId: null,
    nextIsDjPairing: false,
    track: {
      id: 'a',
      title: 'A',
      artist: '',
      durationSec: 1800,
      energy: 5,
      bpm: null,
      key: null,
    },
  },
  {
    id: 2,
    position: 1,
    locked: false,
    targetEnergy: null,
    transitionScore: null,
    nextPairingId: null,
    nextIsDjPairing: false,
    track: {
      id: 'b',
      title: 'B',
      artist: '',
      durationSec: 1800,
      energy: 5,
      bpm: null,
      key: null,
    },
  },
];

describe('TargetEditor', () => {
  it('opens the popover, edits overlap live, and exposes save/undo dirty state', () => {
    const onOpenChange = vi.fn();
    const onSettingsChange = vi.fn();
    const onSave = vi.fn();
    const onUndo = vi.fn();
    render(
      <TargetEditor
        settings={{ targetDurationSec: 3600, avgTransitionOverlapSec: 8 }}
        projection={projectTarget(slots, {
          targetDurationSec: 3600,
          avgTransitionOverlapSec: 8,
        })}
        dirty
        saving={false}
        open
        onOpenChange={onOpenChange}
        onSettingsChange={onSettingsChange}
        onSave={onSave}
        onUndo={onUndo}
      />,
    );

    expect(screen.getByTestId('target-popover')).toBeInTheDocument();
    expect(screen.getByTestId('target-pill')).toHaveTextContent('60:00');
    fireEvent.change(screen.getByRole('slider'), { target: { value: '20' } });
    expect(onSettingsChange).toHaveBeenCalledWith({
      targetDurationSec: 3600,
      avgTransitionOverlapSec: 20,
    });
    expect(screen.getByText('Sum of track durations')).toBeInTheDocument();
    expect(screen.getByText('Projected playing time')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onSave).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onUndo).toHaveBeenCalled();
  });

  it('preset chips update the draft target immediately', () => {
    const onSettingsChange = vi.fn();
    render(
      <TargetEditor
        settings={{ targetDurationSec: 3600, avgTransitionOverlapSec: 8 }}
        projection={null}
        dirty={false}
        saving={false}
        open
        onOpenChange={vi.fn()}
        onSettingsChange={onSettingsChange}
        onSave={vi.fn()}
        onUndo={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId('target-preset-club-opener'));
    expect(onSettingsChange).toHaveBeenCalledWith({
      targetDurationSec: 2700,
      avgTransitionOverlapSec: 8,
    });
  });
});
