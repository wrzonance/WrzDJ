import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CollectionConfigPanel from '../CollectionConfigPanel';
import { api } from '@/lib/api';
import type { CollectionSettingsResponse } from '@/lib/api';
import type { PreEventEventShape } from '../PreEventEventShape';

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
  tidal_sync_enabled: false,
  tidal_collection_playlist_id: null,
  tidal_collection_bidirectional: false,
};

describe('CollectionConfigPanel', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('saves valid event dates and submission caps using the event code', async () => {
    const patch = vi.spyOn(api, 'patchCollectionSettings').mockResolvedValue(response);
    const onEventChange = vi.fn();
    render(
      <CollectionConfigPanel
        event={event}
        tidalConnected={false}
        tidalIntegrationEnabled
        onEventChange={onEventChange}
      />,
    );
    fireEvent.change(screen.getByLabelText('Collection opens at'), { target: { value: '2026-06-01T10:30' } });
    fireEvent.change(screen.getByLabelText('Live starts at'), { target: { value: '2026-06-01T11:30' } });
    fireEvent.change(screen.getByLabelText('Submission cap per guest'), { target: { value: '12' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));

    await waitFor(() => expect(patch).toHaveBeenCalledWith('PARTY', {
      collection_opens_at: new Date('2026-06-01T10:30').toISOString(),
      live_starts_at: new Date('2026-06-01T11:30').toISOString(),
      submission_cap_per_guest: 12,
    }));
    expect(onEventChange).toHaveBeenCalledWith(response);
    expect(await screen.findByText('Settings saved.')).toBeInTheDocument();
  });

  it('rejects collection dates that start after the live phase without calling the API', async () => {
    const patch = vi.spyOn(api, 'patchCollectionSettings');
    render(
      <CollectionConfigPanel
        event={event}
        tidalConnected={false}
        tidalIntegrationEnabled
        onEventChange={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText('Collection opens at'), { target: { value: '2026-06-01T12:00' } });
    fireEvent.change(screen.getByLabelText('Live starts at'), { target: { value: '2026-06-01T11:30' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));

    expect(await screen.findByText('Collection opens must be before live starts')).toBeInTheDocument();
    expect(patch).not.toHaveBeenCalled();
  });

  it('shows collection sync only when Tidal is connected and integration is enabled', () => {
    const { rerender } = render(
      <CollectionConfigPanel event={event} tidalConnected onEventChange={vi.fn()} tidalIntegrationEnabled={false} />,
    );
    expect(screen.queryByText('Tidal Collection Sync')).not.toBeInTheDocument();

    rerender(
      <CollectionConfigPanel event={event} tidalConnected onEventChange={vi.fn()} tidalIntegrationEnabled />,
    );
    expect(screen.getByText('Tidal Collection Sync')).toBeInTheDocument();
  });

  it('reports how many tracks were queued after syncing the collection', async () => {
    vi.spyOn(api, 'syncCollectionToTidal').mockResolvedValue({ queued: 1 });
    render(
      <CollectionConfigPanel
        event={{ ...event, tidal_sync_enabled: true }}
        tidalConnected
        tidalIntegrationEnabled
        onEventChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Sync collection to Tidal' }));

    expect(await screen.findByText('Queued 1 track for sync.')).toBeInTheDocument();
  });
});
