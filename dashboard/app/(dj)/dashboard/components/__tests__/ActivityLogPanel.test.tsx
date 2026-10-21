import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ActivityLogPanel } from '../ActivityLogPanel';
import type { ActivityLogEntry } from '@/lib/api/types';

const entries: ActivityLogEntry[] = [
  {
    id: 1,
    created_at: '2026-01-01T12:00:00Z',
    event_code: 'PARTY',
    level: 'warning',
    message: 'Tidal sync needs attention',
    source: 'tidal',
  },
  {
    id: 2,
    created_at: '2026-01-01T12:01:00Z',
    event_code: 'PARTY',
    level: 'error',
    message: 'Beatport sync failed',
    source: 'beatport',
  },
  {
    id: 3,
    created_at: '2026-01-01T12:02:00Z',
    event_code: 'PARTY',
    level: 'info',
    message: 'Bridge connected',
    source: 'bridge',
  },
];

describe('ActivityLogPanel', () => {
  it('starts collapsed, shows warning/error count, and expands entries on request', () => {
    render(<ActivityLogPanel entries={entries} />);

    expect(screen.getByText('2 warnings')).toBeInTheDocument();
    expect(screen.queryByText('Tidal sync needs attention')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Expand'));

    expect(screen.getByText('Collapse')).toBeInTheDocument();
    expect(screen.getByText('Tidal sync needs attention')).toBeInTheDocument();
    expect(screen.getByText('Beatport sync failed')).toBeInTheDocument();
    expect(screen.getByText('Bridge connected')).toBeInTheDocument();
  });

  it('shows an empty state when the expanded log has no entries', () => {
    render(<ActivityLogPanel entries={[]} />);

    fireEvent.click(screen.getByText('Expand'));

    expect(screen.getByText('No recent activity')).toBeInTheDocument();
    expect(screen.queryByText(/warning/)).not.toBeInTheDocument();
  });
});
