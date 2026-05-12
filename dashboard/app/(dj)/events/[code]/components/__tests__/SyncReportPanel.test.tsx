import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { SyncReportPanel } from '../SyncReportPanel';
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
    status: 'not_found',
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

const defaultProps = {
  connectedServices: ['tidal', 'beatport'],
  expanded: false,
  onToggleExpanded: vi.fn(),
  focusedRequestId: null,
  onClearFocus: vi.fn(),
  onRetrySync: vi.fn(),
  onOpenTidalPicker: vi.fn(),
  onOpenBeatportPicker: vi.fn(),
};

describe('SyncReportPanel', () => {
  it('renders nothing when no connected services', () => {
    const requests = [
      makeRequest({
        sync_results_json: makeSyncResults([{ service: 'tidal', status: 'not_found' }]),
      }),
    ];
    const { container } = render(
      <SyncReportPanel {...defaultProps} connectedServices={[]} requests={requests} />
    );
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing when all requests are fully synced', () => {
    const requests = [
      makeRequest({
        sync_results_json: makeSyncResults([
          { service: 'tidal', status: 'added' },
          { service: 'beatport', status: 'matched' },
        ]),
      }),
    ];
    const { container } = render(
      <SyncReportPanel {...defaultProps} requests={requests} />
    );
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing when no accepted requests', () => {
    const requests = [
      makeRequest({
        status: 'new',
        sync_results_json: makeSyncResults([{ service: 'tidal', status: 'not_found' }]),
      }),
    ];
    const { container } = render(
      <SyncReportPanel {...defaultProps} requests={requests} />
    );
    expect(container.innerHTML).toBe('');
  });

  it('renders collapsed header with summary when issues exist', () => {
    const requests = [
      makeRequest({
        sync_results_json: makeSyncResults([
          { service: 'tidal', status: 'not_found' },
          { service: 'beatport', status: 'not_found' },
        ]),
      }),
      makeRequest({
        id: 2,
        sync_results_json: makeSyncResults([
          { service: 'tidal', status: 'error', error: 'timeout' },
        ]),
      }),
    ];
    render(<SyncReportPanel {...defaultProps} requests={requests} />);
    expect(screen.getByText('Sync Report')).toBeDefined();
    expect(screen.getByText('2 tracks missing, 1 error')).toBeDefined();
  });

  it('does not show request rows when collapsed', () => {
    const requests = [
      makeRequest({
        sync_results_json: makeSyncResults([{ service: 'tidal', status: 'not_found' }]),
      }),
    ];
    render(<SyncReportPanel {...defaultProps} expanded={false} requests={requests} />);
    expect(screen.queryByText('Test Song')).toBeNull();
  });

  it('shows request rows when expanded', () => {
    const requests = [
      makeRequest({
        sync_results_json: makeSyncResults([{ service: 'tidal', status: 'not_found' }]),
      }),
    ];
    render(<SyncReportPanel {...defaultProps} expanded={true} requests={requests} />);
    expect(screen.getByText('Test Song')).toBeDefined();
    expect(screen.getByText('Test Artist')).toBeDefined();
  });

  it('calls onToggleExpanded when header clicked', () => {
    const onToggleExpanded = vi.fn();
    const requests = [
      makeRequest({
        sync_results_json: makeSyncResults([{ service: 'tidal', status: 'not_found' }]),
      }),
    ];
    render(
      <SyncReportPanel
        {...defaultProps}
        onToggleExpanded={onToggleExpanded}
        requests={requests}
      />
    );
    fireEvent.click(screen.getByText('Sync Report'));
    expect(onToggleExpanded).toHaveBeenCalledOnce();
  });

  it('shows "Missing" label for not_found entries', () => {
    const requests = [
      makeRequest({
        sync_results_json: makeSyncResults([
          { service: 'tidal', status: 'not_found' },
          { service: 'beatport', status: 'not_found' },
        ]),
      }),
    ];
    render(<SyncReportPanel {...defaultProps} expanded={true} requests={requests} />);
    expect(screen.getByText('Tidal: Missing')).toBeDefined();
    expect(screen.getByText('Beatport: Missing')).toBeDefined();
  });

  it('shows "Error" label for error entries with retry button', () => {
    const onRetrySync = vi.fn();
    const requests = [
      makeRequest({
        sync_results_json: makeSyncResults([
          { service: 'tidal', status: 'error', error: 'API timeout' },
        ]),
      }),
    ];
    render(
      <SyncReportPanel
        {...defaultProps}
        expanded={true}
        onRetrySync={onRetrySync}
        requests={requests}
      />
    );
    const errorBtn = screen.getByText('Tidal: Error');
    expect(errorBtn).toBeDefined();
    fireEvent.click(errorBtn);
    expect(onRetrySync).toHaveBeenCalledWith(1);
  });

  it('shows "Synced" for added/matched entries with confidence', () => {
    const requests = [
      makeRequest({
        sync_results_json: makeSyncResults([
          { service: 'tidal', status: 'not_found' },
          { service: 'beatport', status: 'matched', confidence: 0.92 },
        ]),
      }),
    ];
    render(<SyncReportPanel {...defaultProps} expanded={true} requests={requests} />);
    expect(screen.getByText('Beatport: Synced (92%)')).toBeDefined();
  });

  it('renders clickable link for synced entry with URL', () => {
    const requests = [
      makeRequest({
        sync_results_json: makeSyncResults([
          { service: 'tidal', status: 'not_found' },
          { service: 'beatport', status: 'matched', url: 'https://beatport.com/track/123' },
        ]),
      }),
    ];
    render(<SyncReportPanel {...defaultProps} expanded={true} requests={requests} />);
    const link = screen.getByText(/Beatport: Synced/);
    expect(link.tagName).toBe('A');
    expect(link.getAttribute('href')).toBe('https://beatport.com/track/123');
  });

  it('calls onOpenTidalPicker when Tidal Missing button clicked', () => {
    const onOpenTidalPicker = vi.fn();
    const requests = [
      makeRequest({
        sync_results_json: makeSyncResults([{ service: 'tidal', status: 'not_found' }]),
      }),
    ];
    render(
      <SyncReportPanel
        {...defaultProps}
        expanded={true}
        onOpenTidalPicker={onOpenTidalPicker}
        requests={requests}
      />
    );
    fireEvent.click(screen.getByText('Tidal: Missing'));
    expect(onOpenTidalPicker).toHaveBeenCalledWith(1);
  });

  it('highlights focused request row', () => {
    const requests = [
      makeRequest({
        sync_results_json: makeSyncResults([{ service: 'tidal', status: 'not_found' }]),
      }),
    ];
    const { container } = render(
      <SyncReportPanel
        {...defaultProps}
        expanded={true}
        focusedRequestId={1}
        requests={requests}
      />
    );
    // The focused row should have a distinct background color (CSS var)
    const row = container.querySelector('[style*="var(--color-primary-subtle)"]');
    expect(row).not.toBeNull();
  });

  it('calls onOpenBeatportPicker when Beatport Missing button clicked', () => {
    const onOpenBeatportPicker = vi.fn();
    const requests = [
      makeRequest({
        sync_results_json: makeSyncResults([{ service: 'beatport', status: 'not_found' }]),
      }),
    ];
    render(
      <SyncReportPanel
        {...defaultProps}
        expanded={true}
        onOpenBeatportPicker={onOpenBeatportPicker}
        requests={requests}
      />
    );
    fireEvent.click(screen.getByText('Beatport: Missing'));
    expect(onOpenBeatportPicker).toHaveBeenCalledWith(1);
  });

  it('handles only missing count in summary', () => {
    const requests = [
      makeRequest({
        sync_results_json: makeSyncResults([{ service: 'tidal', status: 'not_found' }]),
      }),
    ];
    render(<SyncReportPanel {...defaultProps} requests={requests} />);
    expect(screen.getByText('1 track missing')).toBeDefined();
  });
});
