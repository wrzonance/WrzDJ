import { render, screen, waitFor } from '@testing-library/react';
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
vi.mock('@/lib/api', () => ({
  api: {
    listSets: () => mockListSets(),
    createSet: vi.fn(),
    deleteSet: vi.fn(),
    renameSet: vi.fn(),
  },
}));

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ isAuthenticated: true, isLoading: false, role: 'dj' }),
}));

describe('SetbuilderPage', () => {
  beforeEach(() => {
    mockListSets.mockReset();
  });

  it('renders the empty state when there are no sets', async () => {
    mockListSets.mockResolvedValue([]);
    render(<SetbuilderPage />);
    await waitFor(() => {
      expect(screen.getByText(/no sets yet/i)).toBeInTheDocument();
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
        created_at: '2026-06-07T00:00:00Z',
        updated_at: '2026-06-07T00:00:00Z',
      },
    ]);
    render(<SetbuilderPage />);
    await waitFor(() => {
      expect(screen.getByText('Friday Wedding')).toBeInTheDocument();
    });
  });
});
