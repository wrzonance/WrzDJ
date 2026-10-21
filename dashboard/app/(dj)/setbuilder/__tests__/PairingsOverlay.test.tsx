import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Pairing, PairingsState, PoolTrack, SetSlotOut } from '@/lib/api/types';
import PairingsOverlay from '../components/pairings/PairingsOverlay';

const apiMocks = vi.hoisted(() => ({
  getPairings: vi.fn(),
  getPool: vi.fn(),
  getSetSlots: vi.fn(),
  updatePairing: vi.fn(),
  deletePairing: vi.fn(),
}));

vi.mock('@/lib/api', () => ({ api: apiMocks }));

const tracks = [
  { id: 'from', title: 'Neon Lights', artist: 'DJ One', bpm: 120, key: '8A', camelot: '8A', energy: 5 },
  { id: 'into', title: 'Night Drive', artist: 'DJ Two', bpm: 124, key: '9A', camelot: '9A', energy: 6 },
];

function makePairing(id: number, fromTitle: string): Pairing {
  return {
    id,
    from_track_id: 'from',
    into_track_id: 'into',
    from_track: { ...tracks[0], title: fromTitle },
    into_track: tracks[1],
    note: 'Blend on the outro',
    cue_in_sec: null,
    tags: [],
    use_count: 2,
  } as unknown as Pairing;
}

const slots = [
  { id: 1, position: 0, track_id: 'from', title: 'Neon Lights', artist: 'DJ One' },
  { id: 2, position: 1, track_id: 'into', title: 'Night Drive', artist: 'DJ Two' },
] as SetSlotOut[];

let pairings: Pairing[];

function renderOverlay(onClose = vi.fn(), onChanged = vi.fn(), onJumpSlot = vi.fn()) {
  render(
    <PairingsOverlay
      setId={3}
      open
      initialPairingId={null}
      onClose={onClose}
      onChanged={onChanged}
      onJumpSlot={onJumpSlot}
    />,
  );
  return { onClose, onChanged, onJumpSlot };
}

beforeEach(() => {
  pairings = [makePairing(12, 'Neon Lights'), makePairing(13, 'Sunset Road')];
  apiMocks.getPairings.mockImplementation(async () => ({
    count: pairings.length,
    pairings: [...pairings],
  }) as PairingsState);
  apiMocks.getPool.mockResolvedValue({ tracks: [] } as { tracks: PoolTrack[] });
  apiMocks.getSetSlots.mockResolvedValue(slots);
  apiMocks.updatePairing.mockImplementation(async (_setId, id, patch) => {
    pairings = pairings.map((pairing) => pairing.id === id ? { ...pairing, ...patch } : pairing);
    return pairings.find((pairing) => pairing.id === id)!;
  });
  apiMocks.deletePairing.mockImplementation(async (_setId, id) => {
    pairings = pairings.filter((pairing) => pairing.id !== id);
  });
});

afterEach(() => vi.clearAllMocks());

describe('PairingsOverlay', () => {
  it('filters saved pairings by track, note, and tag text', async () => {
    pairings = [
      { ...makePairing(12, 'Neon Lights'), note: 'Warmup blend' },
      { ...makePairing(13, 'Sunset Road'), note: 'Peak outro blend', tags: ['Afterhours'] },
    ];
    renderOverlay();
    expect(await screen.findByRole('button', { name: /Neon Lights/ })).toBeInTheDocument();
    const search = screen.getByPlaceholderText('Search saved pairings...');
    fireEvent.change(search, { target: { value: 'sunset' } });
    expect(await screen.findByRole('button', { name: /Sunset Road/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Neon Lights/ })).not.toBeInTheDocument();

    fireEvent.change(search, { target: { value: 'outro' } });
    expect(await screen.findByRole('button', { name: /Sunset Road/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Neon Lights/ })).not.toBeInTheDocument();

    fireEvent.change(search, { target: { value: 'AFTERHOURS' } });
    expect(await screen.findByRole('button', { name: /Sunset Road/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Neon Lights/ })).not.toBeInTheDocument();
  });

  it('shows compatibility metrics and track-ID fallbacks when related tracks are missing', async () => {
    const missingTracks = {
      ...makePairing(14, 'Gone track'),
      from_track_id: 'missing-from',
      into_track_id: 'missing-into',
      from_track: null,
      into_track: null,
    };
    pairings = [makePairing(12, 'Neon Lights'), missingTracks];
    renderOverlay();

    const compatiblePairing = await screen.findByRole('button', { name: /Neon Lights/ });
    expect(compatiblePairing).toHaveTextContent('3.2% BPM');
    expect(compatiblePairing).toHaveTextContent('Adjacent · ±1');

    const fallbackPairing = screen.getByRole('button', { name: /missing-from/ });
    expect(fallbackPairing).toHaveTextContent('missing-from');
    expect(fallbackPairing).toHaveTextContent('missing-into');
    expect(fallbackPairing).toHaveTextContent('Unknown');
    expect(fallbackPairing).toHaveTextContent('? BPM');
    expect(fallbackPairing).toHaveTextContent('?');
  });

  it('saves note edits through the pairing API', async () => {
    renderOverlay();
    await screen.findByRole('button', { name: /Neon Lights/ });
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    const noteEditor = await screen.findByRole('textbox', { name: 'Pairing note' });
    expect(noteEditor).toHaveValue('Blend on the outro');
    fireEvent.change(noteEditor, { target: { value: 'Use the long outro' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMocks.updatePairing).toHaveBeenCalledWith(3, 12, { note: 'Use the long outro' }));
    expect(await screen.findByText('Use the long outro')).toBeInTheDocument();
  });

  it('deletes a pairing and reports the updated count', async () => {
    const { onChanged } = renderOverlay();
    await screen.findByRole('button', { name: /Neon Lights/ });
    fireEvent.click(screen.getByRole('button', { name: 'Delete pairing' }));
    await waitFor(() => expect(apiMocks.deletePairing).toHaveBeenCalledWith(3, 12));
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith(1));
    expect(await screen.findByRole('button', { name: /Sunset Road/ })).toBeInTheDocument();
  });

  it('keeps a failed delete visible and retryable', async () => {
    let rejectDelete!: (error: Error) => void;
    apiMocks.deletePairing.mockImplementationOnce(() => new Promise((_, reject) => {
      rejectDelete = reject;
    }));
    const { onChanged } = renderOverlay();
    await screen.findByRole('button', { name: /Neon Lights/ });

    fireEvent.click(screen.getByRole('button', { name: 'Delete pairing' }));
    expect(await screen.findByRole('button', { name: 'Deleting pairing' })).toBeDisabled();
    expect(apiMocks.deletePairing).toHaveBeenCalledTimes(1);

    await act(async () => rejectDelete(new Error('provider detail omitted')));

    expect(await screen.findByText('Failed to delete pairing.')).toBeInTheDocument();
    expect(screen.queryByText('provider detail omitted')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Neon Lights/ })).toBeInTheDocument();
    expect(onChanged).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Delete pairing' }));
    await waitFor(() => expect(apiMocks.deletePairing).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole('button', { name: /Neon Lights/ })).not.toBeInTheDocument());
    expect(onChanged).toHaveBeenCalledWith(1);
  });

  it('jumps to the adjacent slot and closes the overlay', async () => {
    const { onClose, onJumpSlot } = renderOverlay();
    await screen.findByRole('button', { name: /Neon Lights/ });
    fireEvent.click(screen.getByRole('button', { name: 'Jump' }));
    expect(onJumpSlot).toHaveBeenCalledWith(0);
    expect(onClose).toHaveBeenCalledOnce();
  });
});
