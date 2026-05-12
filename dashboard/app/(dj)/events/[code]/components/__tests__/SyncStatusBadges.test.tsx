import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { SyncStatusBadges } from '../SyncStatusBadges';
import type { SongRequest, SyncResultEntry } from '@/lib/api-types';

function makeRequest(overrides: Partial<SongRequest> = {}): SongRequest {
  return {
    id: 1,
    event_id: 1,
    song_title: 'Test Song',
    artist: 'Test Artist',
    source: 'spotify',
    source_url: null,
    artwork_url: null,
    note: null,
    nickname: null,
    status: 'accepted',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    is_duplicate: false,
    raw_search_query: null,
    sync_results_json: null,
    vote_count: 0,
    priority_score: null,
    genre: null,
    bpm: null,
    musical_key: null,
    ...overrides,
  };
}

function makeSyncResults(entries: Partial<SyncResultEntry>[]): string {
  const full: SyncResultEntry[] = entries.map((e) => ({
    service: 'tidal',
    status: 'added',
    track_id: null,
    track_title: null,
    track_artist: null,
    confidence: null,
    url: null,
    duration_seconds: null,
    playlist_id: null,
    error: null,
    error_code: null,
    extra: null,
    ...e,
  }));
  return JSON.stringify(full);
}

describe('SyncStatusBadges', () => {
  const defaultProps = {
    connectedServices: ['tidal', 'beatport'],
    syncingRequest: null,
    onSyncToTidal: vi.fn(),
    onOpenTidalPicker: vi.fn(),
    onScrollToSyncReport: vi.fn(),
  };

  it('renders nothing when request status is not accepted', () => {
    const { container } = render(
      <SyncStatusBadges {...defaultProps} request={makeRequest({ status: 'new' })} />
    );
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing when no services connected', () => {
    const { container } = render(
      <SyncStatusBadges {...defaultProps} connectedServices={[]} request={makeRequest()} />
    );
    expect(container.innerHTML).toBe('');
  });

  it('renders green T for Tidal added status', () => {
    const request = makeRequest({
      sync_results_json: makeSyncResults([{ service: 'tidal', status: 'added' }]),
    });
    render(<SyncStatusBadges {...defaultProps} request={request} />);
    const badge = screen.getByTitle('Synced to Tidal');
    expect(badge.textContent).toBe('T');
    expect(badge.style.color).toBe('var(--color-success)'); // was #10b981
  });

  it('renders green B for Beatport matched status', () => {
    const request = makeRequest({
      sync_results_json: makeSyncResults([{ service: 'beatport', status: 'matched' }]),
    });
    render(<SyncStatusBadges {...defaultProps} request={request} />);
    const badge = screen.getByTitle('Found on Beatport');
    expect(badge.textContent).toBe('B');
  });

  it('renders clickable B link when Beatport matched with URL', () => {
    const request = makeRequest({
      sync_results_json: makeSyncResults([
        { service: 'beatport', status: 'matched', url: 'https://beatport.com/track/123' },
      ]),
    });
    render(<SyncStatusBadges {...defaultProps} request={request} />);
    const link = screen.getByTitle('Available on Beatport - click to view');
    expect(link.tagName).toBe('A');
    expect(link.getAttribute('href')).toBe('https://beatport.com/track/123');
    expect(link.getAttribute('target')).toBe('_blank');
  });

  it('renders orange T? button for Tidal not_found', () => {
    const request = makeRequest({
      sync_results_json: makeSyncResults([{ service: 'tidal', status: 'not_found' }]),
    });
    render(<SyncStatusBadges {...defaultProps} request={request} />);
    const badge = screen.getByTitle('Missing from Tidal - click to link manually');
    expect(badge.textContent).toBe('T?');
  });

  it('renders orange B? button for Beatport not_found', () => {
    const request = makeRequest({
      sync_results_json: makeSyncResults([{ service: 'beatport', status: 'not_found' }]),
    });
    render(<SyncStatusBadges {...defaultProps} request={request} />);
    const badge = screen.getByTitle('Missing from Beatport - click for details');
    expect(badge.textContent).toBe('B?');
  });

  it('renders red T! button for Tidal error', () => {
    const request = makeRequest({
      sync_results_json: makeSyncResults([{ service: 'tidal', status: 'error' }]),
    });
    render(<SyncStatusBadges {...defaultProps} request={request} />);
    const badge = screen.getByTitle('Sync failed - click to retry');
    expect(badge.textContent).toBe('T!');
  });

  it('shows sync button when no tidal status yet', () => {
    const request = makeRequest();
    render(<SyncStatusBadges {...defaultProps} request={request} />);
    const badge = screen.getByTitle('Sync to Tidal');
    expect(badge.textContent).toBe('T');
  });

  it('calls onSyncToTidal when sync button clicked', () => {
    const onSyncToTidal = vi.fn();
    const request = makeRequest();
    render(
      <SyncStatusBadges {...defaultProps} onSyncToTidal={onSyncToTidal} request={request} />
    );
    fireEvent.click(screen.getByTitle('Sync to Tidal'));
    expect(onSyncToTidal).toHaveBeenCalledWith(1);
  });

  it('calls onOpenTidalPicker when not_found badge clicked', () => {
    const onOpenTidalPicker = vi.fn();
    const request = makeRequest({
      sync_results_json: makeSyncResults([{ service: 'tidal', status: 'not_found' }]),
    });
    render(
      <SyncStatusBadges {...defaultProps} onOpenTidalPicker={onOpenTidalPicker} request={request} />
    );
    fireEvent.click(screen.getByTitle('Missing from Tidal - click to link manually'));
    expect(onOpenTidalPicker).toHaveBeenCalledWith(1);
  });

  it('calls onScrollToSyncReport when Beatport not_found badge clicked', () => {
    const onScrollToSyncReport = vi.fn();
    const request = makeRequest({
      sync_results_json: makeSyncResults([{ service: 'beatport', status: 'not_found' }]),
    });
    render(
      <SyncStatusBadges
        {...defaultProps}
        onScrollToSyncReport={onScrollToSyncReport}
        request={request}
      />
    );
    fireEvent.click(screen.getByTitle('Missing from Beatport - click for details'));
    expect(onScrollToSyncReport).toHaveBeenCalledWith(1);
  });

  it('shows syncing indicator when syncing', () => {
    const request = makeRequest();
    render(<SyncStatusBadges {...defaultProps} syncingRequest={1} request={request} />);
    const badge = screen.getByTitle('Sync to Tidal');
    expect(badge.textContent).toBe('...');
    expect(badge).toBeDisabled();
  });

  it('renders both Tidal and Beatport badges when both connected', () => {
    const request = makeRequest({
      sync_results_json: makeSyncResults([
        { service: 'tidal', status: 'added' },
        { service: 'beatport', status: 'matched' },
      ]),
    });
    render(<SyncStatusBadges {...defaultProps} request={request} />);
    expect(screen.getByTitle('Synced to Tidal')).toBeDefined();
    expect(screen.getByTitle('Found on Beatport')).toBeDefined();
  });

  it('renders only Tidal badge when only Tidal connected', () => {
    const request = makeRequest({
      sync_results_json: makeSyncResults([{ service: 'tidal', status: 'added' }]),
    });
    render(
      <SyncStatusBadges {...defaultProps} connectedServices={['tidal']} request={request} />
    );
    expect(screen.getByTitle('Synced to Tidal')).toBeDefined();
    expect(screen.queryByText('B')).toBeNull();
  });
});
