import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import KioskLinkPage from '../page';

// Mock next/navigation — router object must be referentially stable
// so useEffect deps don't re-trigger on every render
const mockPush = vi.fn();
const mockRouter = { push: mockPush };
const mockParams = { code: 'ABC234' };
vi.mock('next/navigation', () => ({
  useRouter: () => mockRouter,
  useParams: () => mockParams,
}));

// Mock auth
let mockIsAuthenticated = true;
let mockIsLoading = false;
let mockRole: string | null = 'dj';
vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    isAuthenticated: mockIsAuthenticated,
    isLoading: mockIsLoading,
    role: mockRole,
  }),
}));

// Mock API
const mockGetEvents = vi.fn();
const mockCompleteKioskPairing = vi.fn();
vi.mock('@/lib/api', () => ({
  api: {
    getEvents: (...args: unknown[]) => mockGetEvents(...args),
    completeKioskPairing: (...args: unknown[]) => mockCompleteKioskPairing(...args),
  },
}));

describe('KioskLinkPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockIsAuthenticated = true;
    mockIsLoading = false;
    mockRole = 'dj';
    mockGetEvents.mockResolvedValue([
      {
        id: 1, code: 'EVT001', name: 'Friday Night', is_active: true,
        created_at: '2026-02-20T00:00:00Z', expires_at: '2026-02-21T00:00:00Z',
      },
      {
        id: 2, code: 'EVT002', name: 'Saturday Bash', is_active: true,
        created_at: '2026-02-20T00:00:00Z', expires_at: '2026-02-21T00:00:00Z',
      },
    ]);
    mockCompleteKioskPairing.mockResolvedValue({
      id: 1, name: null, event_code: 'EVT001', status: 'active',
    });
  });

  it('redirects to login when not authenticated', async () => {
    mockIsAuthenticated = false;
    render(<KioskLinkPage />);

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/login?redirect=/kiosk-link/ABC234');
    });
  });

  it('redirects pending accounts without loading events or allowing pairing', async () => {
    // Regression for baseline 57cfcdc6867f: pending accounts could start kiosk pairing.
    mockRole = 'pending';
    render(<KioskLinkPage />);

    await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/pending'));
    expect(mockGetEvents).not.toHaveBeenCalled();
    expect(mockCompleteKioskPairing).not.toHaveBeenCalled();
    expect(screen.queryByText('Friday Night')).not.toBeInTheDocument();
  });

  it('waits for authentication to finish before loading events', async () => {
    mockIsLoading = true;
    const { rerender } = render(<KioskLinkPage />);

    expect(screen.getByText('Loading...')).toBeInTheDocument();
    expect(mockGetEvents).not.toHaveBeenCalled();

    mockIsLoading = false;
    rerender(<KioskLinkPage />);
    await waitFor(() => expect(screen.getByText('Friday Night')).toBeInTheDocument());
    expect(mockGetEvents).toHaveBeenCalledTimes(1);
  });

  it('displays event list when authenticated', async () => {
    render(<KioskLinkPage />);

    await waitFor(() => {
      expect(screen.getByText('Friday Night')).toBeInTheDocument();
      expect(screen.getByText('Saturday Bash')).toBeInTheDocument();
    });
  });

  it('calls completeKioskPairing on confirm', async () => {
    render(<KioskLinkPage />);

    await waitFor(() => {
      expect(screen.getByText('Friday Night')).toBeInTheDocument();
    });

    // Click the button (closest button parent of the text)
    const btn = screen.getByText('Friday Night').closest('button')!;
    fireEvent.click(btn);

    await waitFor(() => {
      expect(mockCompleteKioskPairing).toHaveBeenCalledWith('ABC234', 'EVT001');
    });
  });

  it('shows success message after pairing', async () => {
    render(<KioskLinkPage />);

    await waitFor(() => {
      expect(screen.getByText('Friday Night')).toBeInTheDocument();
    });

    const btn = screen.getByText('Friday Night').closest('button')!;
    fireEvent.click(btn);

    // Wait for async pairing + state transition
    await waitFor(() => {
      expect(screen.getByText(/Kiosk paired/i)).toBeInTheDocument();
    });
  });

  it('shows error for expired code (410)', async () => {
    const err = new Error('Pairing code has expired');
    (err as unknown as Record<string, unknown>).status = 410;
    mockCompleteKioskPairing.mockRejectedValue(err);

    render(<KioskLinkPage />);

    await waitFor(() => {
      expect(screen.getByText('Friday Night')).toBeInTheDocument();
    });

    const btn = screen.getByText('Friday Night').closest('button')!;
    fireEvent.click(btn);

    await waitFor(() => {
      expect(screen.getByText(/expired/i)).toBeInTheDocument();
    });
  });

  it('event selector buttons use theme-safe background and text color', async () => {
    render(<KioskLinkPage />);

    await waitFor(() => {
      const btn = screen.getByText('Friday Night').closest('button')!;
      expect(btn).toHaveAttribute('style', expect.stringContaining('var(--surface-raised)'));
      expect(btn).toHaveAttribute('style', expect.stringContaining('var(--text)'));
    });
  });

  it('try again button uses theme-safe background', async () => {
    const err = new Error('Test error');
    mockCompleteKioskPairing.mockRejectedValue(err);
    render(<KioskLinkPage />);

    await waitFor(() => screen.getByText('Friday Night'));
    fireEvent.click(screen.getByText('Friday Night').closest('button')!);

    await waitFor(() => {
      const tryAgainBtn = screen.getByRole('button', { name: /try again/i });
      expect(tryAgainBtn).toHaveAttribute('style', expect.stringContaining('var(--surface-raised)'));
    });
  });
});
