import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
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
vi.mock('@/lib/api', () => ({
  api: {
    listSets: () => mockListSets(),
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
