import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/api';
import type { CollectionSettingsResponse } from '@/lib/api';
import type { PreEventEventShape } from '../PreEventEventShape';
import TidalCollectionSyncPanel from '../TidalCollectionSyncPanel';

const event: PreEventEventShape = {
  code: 'PARTY',
  name: 'Birthday Bash',
  collection_opens_at: null,
  live_starts_at: null,
  submission_cap_per_guest: 0,
  collection_phase_override: null,
  phase: 'pre_announce',
  tidal_sync_enabled: false,
  tidal_collection_playlist_id: null,
  tidal_collection_bidirectional: false,
};

const response: CollectionSettingsResponse = {
  collection_opens_at: null,
  live_starts_at: null,
  submission_cap_per_guest: 0,
  collection_phase_override: null,
  phase: 'pre_announce',
  tidal_sync_enabled: true,
  tidal_collection_playlist_id: null,
  tidal_collection_bidirectional: false,
};

describe('TidalCollectionSyncPanel', () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.useRealTimers());

  it('uses the shared bright-accent foreground for the sync action', () => {
    render(
      <TidalCollectionSyncPanel
        event={{ ...event, tidal_sync_enabled: true }}
        onEventChange={vi.fn()}
      />,
    );
    const button = screen.getByRole('button', { name: 'Sync collection to Tidal' });
    expect(button.style.background).toBe('rgb(29, 185, 84)');
    expect(button.style.color).toBe('var(--text-on-bright-accent)');
  });

  // Regression for baseline 57cfcdc6867f: failed setting changes must leave the
  // control retryable, and successful changes must be reflected by the parent.
  it('reports toggle failure and sends the successful retry to the parent', async () => {
    const patch = vi.spyOn(api, 'patchCollectionSettings')
      .mockRejectedValueOnce(new Error('Tidal setting unavailable'))
      .mockResolvedValue(response);
    const onEventChange = vi.fn();
    render(<TidalCollectionSyncPanel event={event} onEventChange={onEventChange} />);
    const checkbox = screen.getByRole('checkbox', { name: /Enable Tidal sync/ });

    fireEvent.click(screen.getByText('Enable Tidal sync for this collection'));
    await act(async () => {});
    expect(patch).toHaveBeenCalledTimes(1);
    expect(patch).toHaveBeenCalledWith('PARTY', { tidal_sync_enabled: true });
    expect(screen.getByText('Tidal setting unavailable')).toBeInTheDocument();
    expect(checkbox).toBeEnabled();

    fireEvent.click(screen.getByText('Enable Tidal sync for this collection'));
    await act(async () => {});
    expect(patch).toHaveBeenNthCalledWith(2, 'PARTY', { tidal_sync_enabled: true });
    expect(onEventChange).toHaveBeenCalledWith(response);
    expect(checkbox).toBeEnabled();
  });

  // Regression for baseline 57cfcdc6867f: rejected syncs must show the failure
  // and return the action button to its retryable state, then clear the message.
  it('shows a sync rejection, restores the action, and clears the error', async () => {
    vi.useFakeTimers();
    vi.spyOn(api, 'syncCollectionToTidal').mockRejectedValue(new Error('Tidal is offline'));
    render(
      <TidalCollectionSyncPanel
        event={{ ...event, tidal_sync_enabled: true }}
        onEventChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Sync collection to Tidal' }));
    expect(screen.getByRole('button', { name: 'Syncing…' })).toBeDisabled();
    await act(async () => {});

    expect(screen.getByText('Tidal is offline')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sync collection to Tidal' })).toBeEnabled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(screen.queryByText('Tidal is offline')).not.toBeInTheDocument();
    vi.useRealTimers();
  });

  // Regression for baseline 57cfcdc6867f: a successful no-op sync reports that
  // there were no new tracks, then removes the transient result after five seconds.
  it('clears the zero-queued result after its transient display window', async () => {
    vi.useFakeTimers();
    const sync = vi.spyOn(api, 'syncCollectionToTidal').mockResolvedValue({ queued: 0 });
    render(
      <TidalCollectionSyncPanel
        event={{ ...event, tidal_sync_enabled: true }}
        onEventChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Sync collection to Tidal' }));
    await act(async () => {});

    expect(sync).toHaveBeenCalledWith('PARTY');
    expect(screen.getByText('All tracks already synced.')).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(screen.queryByText('All tracks already synced.')).not.toBeInTheDocument();
    vi.useRealTimers();
  });
});
