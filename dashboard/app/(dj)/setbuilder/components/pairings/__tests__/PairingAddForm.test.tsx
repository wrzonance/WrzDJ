import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Pairing, PoolTrack } from '@/lib/api/types';
import { PairingAddForm } from '../PairingAddForm';

const pool = [
  {
    id: 1,
    track_id: 'spotify:first',
    title: 'First Song',
    artist: 'First Artist',
    bpm: 120,
    key: '8A',
    camelot: '8A',
    energy: 5,
  },
  {
    id: 2,
    track_id: 'spotify:second',
    title: 'Second Song',
    artist: 'Second Artist',
    bpm: 124,
    key: '9A',
    camelot: '9A',
    energy: 6,
  },
] as PoolTrack[];

function chooseTracks() {
  const pickers = screen.getAllByRole('button', { name: 'Pick a track' });
  fireEvent.click(pickers[0]);
  fireEvent.click(screen.getByRole('button', { name: /First Song/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Pick a track' }));
  fireEvent.click(screen.getByRole('button', { name: /Second Song/ }));
}

describe('PairingAddForm', () => {
  // Regression for baseline 57cfcdc6867f: creating a pairing must preserve both
  // selected track IDs and normalize optional user-entered metadata at save time.
  it('creates a directional two-track pairing with normalized cue, tags, and note', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<PairingAddForm pool={pool} pairings={[]} onCancel={vi.fn()} onSave={onSave} />);

    chooseTracks();
    fireEvent.change(screen.getByLabelText('Cue in seconds'), { target: { value: '-12' } });
    fireEvent.change(screen.getByLabelText('Tags'), { target: { value: ' wedding, #safe, peak ' } });
    fireEvent.change(screen.getByLabelText('Note'), { target: { value: '  Blend after the vocal  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save pairing' }));

    await waitFor(() => expect(onSave).toHaveBeenCalledWith({
      from_track_id: 'spotify:first',
      into_track_id: 'spotify:second',
      cue_in_sec: 0,
      note: 'Blend after the vocal',
      tags: ['wedding', 'safe', 'peak'],
    }));
  });

  // Regression for baseline 57cfcdc6867f: an already-saved directional pairing
  // must remain blocked even when both picker controls could select those tracks.
  it('disables saving an existing directional pairing', () => {
    const existing = {
      from_track_id: 'spotify:first',
      into_track_id: 'spotify:second',
    } as Pairing;
    render(<PairingAddForm pool={pool} pairings={[existing]} onCancel={vi.fn()} onSave={vi.fn()} />);

    chooseTracks();

    expect(screen.getByText(/A pairing already exists/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save pairing' })).toBeDisabled();
  });

  // Regression for baseline 57cfcdc6867f: a rejected parent save must leave the
  // user's pairing draft available for retry; the parent owns the visible error.
  it('keeps the draft intact after save failure so the user can retry', async () => {
    const onSave = vi.fn().mockRejectedValueOnce(new Error('save failed')).mockResolvedValue(undefined);
    render(<PairingAddForm pool={pool} pairings={[]} onCancel={vi.fn()} onSave={onSave} />);

    chooseTracks();
    fireEvent.change(screen.getByLabelText('Note'), { target: { value: '  Retry this blend  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save pairing' }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText('Note')).toHaveValue('  Retry this blend  ');
    expect(screen.getByRole('button', { name: 'Save pairing' })).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: 'Save pairing' }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2));
    expect(onSave.mock.calls[1][0]).toMatchObject({
      from_track_id: 'spotify:first',
      into_track_id: 'spotify:second',
      note: 'Retry this blend',
    });
  });
});
