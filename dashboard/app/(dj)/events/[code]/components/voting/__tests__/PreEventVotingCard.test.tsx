import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PreEventVotingCard } from '../PreEventVotingCard';
import { api } from '@/lib/api';
import type { CollectionSettingsResponse } from '@/lib/api';
import type { Event } from '@/lib/api/types';

const event = (overrides: Partial<Event> = {}) => ({
  code: 'PARTY',
  collection_opens_at: null,
  live_starts_at: null,
  submission_cap_per_guest: 15,
  ...overrides,
} as Event);

const response: CollectionSettingsResponse = {
  collection_opens_at: '2026-06-01T10:30:00Z',
  live_starts_at: null,
  submission_cap_per_guest: 15,
  collection_phase_override: null,
  phase: 'collection',
  tidal_sync_enabled: false,
  tidal_collection_playlist_id: null,
  tidal_collection_bidirectional: false,
};

describe('PreEventVotingCard', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('sends enabled events to the dedicated voting tab', () => {
    const onJumpToTab = vi.fn();
    render(
      <PreEventVotingCard event={event({ collection_opens_at: '2026-06-01T10:30:00Z' })} onEnabled={vi.fn()} onJumpToTab={onJumpToTab} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Open Pre-Event Voting →' }));

    expect(onJumpToTab).toHaveBeenCalledOnce();
    expect(screen.queryByLabelText('Collection opens at')).not.toBeInTheDocument();
  });

  it('requires at least one date before enabling the feature', async () => {
    const patch = vi.spyOn(api, 'patchCollectionSettings');
    render(<PreEventVotingCard event={event()} onEnabled={vi.fn()} onJumpToTab={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Set up pre-event voting' }));
    fireEvent.click(screen.getByRole('button', { name: 'Enable pre-event voting' }));

    expect(await screen.findByText('Set at least an "opens at" or "live starts at" date.')).toBeInTheDocument();
    expect(patch).not.toHaveBeenCalled();
  });

  it('validates dates and saves the enable payload', async () => {
    const patch = vi.spyOn(api, 'patchCollectionSettings').mockResolvedValue(response);
    const onEnabled = vi.fn();
    render(<PreEventVotingCard event={event()} onEnabled={onEnabled} onJumpToTab={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Set up pre-event voting' }));
    fireEvent.change(screen.getByLabelText('Collection opens at'), { target: { value: '2026-06-01T10:30' } });
    fireEvent.click(screen.getByRole('button', { name: 'Enable pre-event voting' }));

    await waitFor(() => expect(patch).toHaveBeenCalledWith('PARTY', {
      collection_opens_at: new Date('2026-06-01T10:30').toISOString(),
      live_starts_at: null,
      submission_cap_per_guest: 15,
    }));
    expect(onEnabled).toHaveBeenCalledWith(response);
  });
});
