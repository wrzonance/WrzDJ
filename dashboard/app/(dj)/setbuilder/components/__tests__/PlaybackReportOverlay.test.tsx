/**
 * PlaybackReportOverlay tests (issue #403) — derive-on-read planned-vs-actual.
 * Covers: the four outcome states (played / skipped / out_of_order / substituted),
 * the summary header, and the explicit "Apply to pairings" action.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import type { PlaybackReport, ApplyPairingFeedback } from '@/lib/api-types';
import PlaybackReportOverlay from '../PlaybackReportOverlay';

const mockApi = vi.hoisted(() => ({
  getPlaybackReport: vi.fn(),
  applyPlaybackPairings: vi.fn(),
}));

vi.mock('@/lib/api', () => ({ api: mockApi }));

function makeReport(overrides: Partial<PlaybackReport> = {}): PlaybackReport {
  return {
    event_id: 7,
    slots: [
      {
        slot_id: 1,
        position: 0,
        track_id: 'tidal:a',
        title: 'Alpha',
        artist: 'AA',
        outcome: 'played',
        play_order: 1,
        played_at: null,
        deck: null,
      },
      {
        slot_id: 2,
        position: 1,
        track_id: 'tidal:b',
        title: 'Bravo',
        artist: 'BB',
        outcome: 'out_of_order',
        play_order: 3,
        played_at: null,
        deck: null,
      },
      {
        slot_id: 3,
        position: 2,
        track_id: 'tidal:c',
        title: 'Charlie',
        artist: 'CC',
        outcome: 'skipped',
        play_order: null,
        played_at: null,
        deck: null,
      },
    ],
    unplanned: [
      {
        play_order: 2,
        title: 'Surprise',
        artist: 'Guest',
        played_at: null,
        deck: null,
        outcome: 'substituted',
      },
    ],
    summary: {
      total_planned: 3,
      total_played: 3,
      played: 2,
      skipped: 1,
      out_of_order: 1,
      unplanned: 1,
    },
    ...overrides,
  };
}

beforeEach(() => {
  mockApi.getPlaybackReport.mockReset();
  mockApi.applyPlaybackPairings.mockReset();
});

describe('PlaybackReportOverlay', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <PlaybackReportOverlay setId={42} open={false} onClose={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
    expect(mockApi.getPlaybackReport).not.toHaveBeenCalled();
  });

  it('renders the four outcome states and the planned/actual tracks', async () => {
    mockApi.getPlaybackReport.mockResolvedValue(makeReport());
    render(<PlaybackReportOverlay setId={42} open onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText('Alpha')).toBeTruthy());
    expect(screen.getByText('Bravo')).toBeTruthy();
    expect(screen.getByText('Charlie')).toBeTruthy();
    expect(screen.getByText('Surprise')).toBeTruthy();

    // Each outcome badge label is present.
    expect(screen.getByText('Played')).toBeTruthy();
    expect(screen.getByText('Out of order')).toBeTruthy();
    expect(screen.getByText('Skipped')).toBeTruthy();
    expect(screen.getByText('Unplanned')).toBeTruthy();
  });

  it('applies pairings via the API and reports the bumped count', async () => {
    mockApi.getPlaybackReport.mockResolvedValue(makeReport());
    const applied: ApplyPairingFeedback = {
      bumped: 2,
      pairings: { count: 0, pairings: [] },
    };
    mockApi.applyPlaybackPairings.mockResolvedValue(applied);
    const onApplied = vi.fn();

    render(<PlaybackReportOverlay setId={42} open onClose={() => {}} onApplied={onApplied} />);
    await waitFor(() => expect(screen.getByText('Alpha')).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: /apply to pairings/i }));

    await waitFor(() => expect(mockApi.applyPlaybackPairings).toHaveBeenCalledWith(42));
    await waitFor(() => expect(screen.getByText(/bumped 2/i)).toBeTruthy());
    expect(onApplied).toHaveBeenCalledWith(2);
  });
});
