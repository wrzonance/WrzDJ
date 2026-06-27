import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import SetbuilderPage from '../page';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const mockListSets = vi.fn();
const mockRenameSet = vi.fn();
const mockDuplicateSet = vi.fn();
const mockGetTasteProfile = vi.fn();
const mockResetTasteProfile = vi.fn();
vi.mock('@/lib/api', () => ({
  api: {
    listSets: () => mockListSets(),
    getSetbuilderTasteProfile: () => mockGetTasteProfile(),
    resetSetbuilderTasteProfile: () => mockResetTasteProfile(),
    createSet: vi.fn(),
    deleteSet: vi.fn(),
    renameSet: (id: number, name: string) => mockRenameSet(id, name),
    duplicateSet: (id: number) => mockDuplicateSet(id),
    shareSet: vi.fn(),
    revokeSetShare: vi.fn(),
  },
}));

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ isAuthenticated: true, isLoading: false, role: 'dj' }),
}));

// ThemeToggle renders inline here (the (dj) layout's floating toggle is
// suppressed on /setbuilder routes to avoid overlapping the topbar actions).
vi.mock('@/components/ThemeToggle', () => ({
  ThemeToggle: () => <button data-testid="theme-toggle-mock">Theme</button>,
}));

describe('SetbuilderPage', () => {
  beforeEach(() => {
    mockListSets.mockReset();
    mockRenameSet.mockReset();
    mockDuplicateSet.mockReset();
    mockGetTasteProfile.mockReset();
    mockResetTasteProfile.mockReset();
    mockGetTasteProfile.mockResolvedValue({
      sample_count: 0,
      min_samples: 5,
      active: false,
      average_energy_delta: null,
      energy_adjustment: 0,
      top_moods: [],
      summary: 'No learned taste profile yet.',
      reset_at: null,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the empty state when there are no sets', async () => {
    mockListSets.mockResolvedValue([]);
    render(<SetbuilderPage />);
    await waitFor(() => {
      expect(screen.getByText(/no sets yet/i)).toBeInTheDocument();
    });
  });

  it('renders the theme toggle inline in the header', async () => {
    mockListSets.mockResolvedValue([]);
    render(<SetbuilderPage />);
    await waitFor(() => {
      expect(screen.getByTestId('theme-toggle-mock')).toBeInTheDocument();
    });
  });

  it('renders set cards from the API', async () => {
    mockListSets.mockResolvedValue([
      {
        id: 1,
        name: 'Friday Wedding',
        event_id: null,
        status: 'draft',
        sharing_mode: 'private',
        share_token: null,
        created_at: '2026-06-07T00:00:00Z',
        updated_at: '2026-06-07T00:00:00Z',
      },
    ]);
    render(<SetbuilderPage />);
    await waitFor(() => {
      expect(screen.getByText('Friday Wedding')).toBeInTheDocument();
    });
  });

  it('keeps the sets list visible when the taste profile fails to load', async () => {
    mockListSets.mockResolvedValue([
      {
        id: 1,
        name: 'Friday Wedding',
        event_id: null,
        status: 'draft',
        sharing_mode: 'private',
        share_token: null,
        created_at: '2026-06-07T00:00:00Z',
        updated_at: '2026-06-07T00:00:00Z',
      },
    ]);
    mockGetTasteProfile.mockRejectedValue(new Error('profile unavailable'));

    render(<SetbuilderPage />);

    await waitFor(() => {
      expect(screen.getByText('Friday Wedding')).toBeInTheDocument();
      expect(screen.queryByText('Failed to load sets')).not.toBeInTheDocument();
    });
  });

  it('renders the compact learned taste profile card', async () => {
    mockListSets.mockResolvedValue([]);
    mockGetTasteProfile.mockResolvedValue({
      sample_count: 8,
      min_samples: 5,
      active: true,
      average_energy_delta: 2,
      energy_adjustment: 1.5,
      top_moods: [{ mood: 'Peak', count: 5 }],
      summary: 'Learned from 8 edits: energy +1.5; top mood Peak.',
      reset_at: null,
    });

    render(<SetbuilderPage />);

    await waitFor(() => {
      expect(screen.getByText('Taste profile')).toBeInTheDocument();
      expect(screen.getAllByText(/energy \+1\.5/i).length).toBeGreaterThan(0);
      expect(screen.getByText('Peak')).toBeInTheDocument();
    });
  });

  it('resets the learned taste profile after confirmation', async () => {
    mockListSets.mockResolvedValue([]);
    mockGetTasteProfile.mockResolvedValue({
      sample_count: 8,
      min_samples: 5,
      active: true,
      average_energy_delta: 2,
      energy_adjustment: 1.5,
      top_moods: [{ mood: 'Peak', count: 5 }],
      summary: 'Learned from 8 edits: energy +1.5; top mood Peak.',
      reset_at: null,
    });
    mockResetTasteProfile.mockResolvedValue({
      sample_count: 0,
      min_samples: 5,
      active: false,
      average_energy_delta: null,
      energy_adjustment: 0,
      top_moods: [],
      summary: 'No learned taste profile yet.',
      reset_at: '2026-06-26T18:00:00Z',
    });
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(<SetbuilderPage />);
    await waitFor(() => expect(screen.getByText('Taste profile')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /reset profile/i }));

    await waitFor(() => {
      expect(mockResetTasteProfile).toHaveBeenCalledTimes(1);
      expect(screen.getByText(/no learned taste profile yet/i)).toBeInTheDocument();
    });
  });

  it('renames a set inline via the API and reflects the new name', async () => {
    mockListSets.mockResolvedValue([
      {
        id: 1,
        name: 'Friday Wedding',
        event_id: null,
        status: 'draft',
        sharing_mode: 'private',
        share_token: null,
        created_at: '2026-06-07T00:00:00Z',
        updated_at: '2026-06-07T00:00:00Z',
      },
    ]);
    mockRenameSet.mockResolvedValue({
      id: 1,
      name: 'Saturday Gala',
      event_id: null,
      status: 'draft',
      sharing_mode: 'private',
      share_token: null,
      created_at: '2026-06-07T00:00:00Z',
      updated_at: '2026-06-07T01:00:00Z',
    });
    render(<SetbuilderPage />);

    await waitFor(() => expect(screen.getByText('Friday Wedding')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /rename/i }));
    const input = screen.getByDisplayValue('Friday Wedding');
    fireEvent.change(input, { target: { value: 'Saturday Gala' } });
    fireEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => {
      expect(mockRenameSet).toHaveBeenCalledWith(1, 'Saturday Gala');
      expect(screen.getByText('Saturday Gala')).toBeInTheDocument();
    });
  });

  it('shows a Shared badge when a set has a share token', async () => {
    mockListSets.mockResolvedValue([
      {
        id: 1,
        name: 'Friday Wedding',
        event_id: null,
        status: 'draft',
        sharing_mode: 'private',
        share_token: 'tok_live',
        created_at: '2026-06-07T00:00:00Z',
        updated_at: '2026-06-07T00:00:00Z',
      },
    ]);
    render(<SetbuilderPage />);
    await waitFor(() => {
      expect(screen.getByText('Shared')).toBeInTheDocument();
    });
  });

  it('duplicates a set and prepends the copy to the list', async () => {
    mockListSets.mockResolvedValue([
      {
        id: 1,
        name: 'Friday Wedding',
        event_id: null,
        status: 'draft',
        sharing_mode: 'private',
        share_token: null,
        created_at: '2026-06-07T00:00:00Z',
        updated_at: '2026-06-07T00:00:00Z',
      },
    ]);
    mockDuplicateSet.mockResolvedValue({
      id: 2,
      name: 'Friday Wedding (copy)',
      event_id: null,
      status: 'draft',
      sharing_mode: 'private',
      share_token: null,
      created_at: '2026-06-08T00:00:00Z',
      updated_at: '2026-06-08T00:00:00Z',
    });
    render(<SetbuilderPage />);
    await waitFor(() => expect(screen.getByText('Friday Wedding')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /duplicate/i }));

    await waitFor(() => {
      expect(mockDuplicateSet).toHaveBeenCalledWith(1);
      expect(screen.getByText('Friday Wedding (copy)')).toBeInTheDocument();
    });
  });
});
