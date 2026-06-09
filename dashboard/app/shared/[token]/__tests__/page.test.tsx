import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import SharedSetPage from '../page';
import type { SharedSetView } from '@/lib/api-types';

const mockGetSharedSet = vi.fn();
vi.mock('@/lib/api', () => ({
  api: {
    getSharedSet: (token: string) => mockGetSharedSet(token),
  },
}));

let mockToken = 'tok_live';
vi.mock('next/navigation', () => ({
  useParams: () => ({ token: mockToken }),
}));

function makeView(overrides: Partial<SharedSetView> = {}): SharedSetView {
  return {
    name: 'Warehouse Closer',
    status: 'draft',
    vibe_theme: 'dark-techno',
    target_duration_sec: 3600,
    bpm_floor: 124,
    bpm_ceiling: 132,
    key_strictness: 0.7,
    slots: [
      {
        position: 1,
        track_id: 'tidal:111',
        locked: true,
        notes: 'opener',
        transition_score: 0.9,
      },
      {
        position: 2,
        track_id: 'tidal:222',
        locked: false,
        notes: null,
        transition_score: null,
      },
    ],
    curve_points: [
      {
        position_sec: 0,
        energy: 4,
        label: 'warmup',
        is_slow_window_start: true,
        is_slow_window_end: false,
      },
    ],
    ...overrides,
  };
}

function renderPage(token = 'tok_live') {
  mockToken = token;
  return render(<SharedSetPage />);
}

describe('SharedSetPage', () => {
  beforeEach(() => {
    mockGetSharedSet.mockReset();
    mockToken = 'tok_live';
  });

  it('renders the view-only set with slots and curve', async () => {
    mockGetSharedSet.mockResolvedValue(makeView());
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('Warehouse Closer')).toBeInTheDocument();
    });
    expect(mockGetSharedSet).toHaveBeenCalledWith('tok_live');
    expect(screen.getByText(/view only/i)).toBeInTheDocument();
    expect(screen.getByText('tidal:111')).toBeInTheDocument();
    expect(screen.getByText('opener')).toBeInTheDocument();
    expect(screen.getByText('warmup')).toBeInTheDocument();
    expect(screen.getByText(/124–132 BPM/)).toBeInTheDocument();
    // no mutation/agent/export affordances
    expect(screen.queryByRole('button', { name: /share|duplicate|export|save|delete/i })).toBeNull();
  });

  it('shows an invalid-link message when the token 404s', async () => {
    mockGetSharedSet.mockRejectedValue(new Error('Not found'));
    renderPage('bad');
    await waitFor(() => {
      expect(screen.getByText(/invalid or has been revoked/i)).toBeInTheDocument();
    });
  });
});
