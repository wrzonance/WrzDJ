import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const mockPush = vi.fn();

// Use a reference object so updates are visible
const params: { token: string | null } = { token: 'validtoken123' };

vi.mock('next/navigation', async () => {
  const actual = await vi.importActual('next/navigation');
  return {
    ...actual,
    useRouter: () => ({ push: mockPush }),
    useSearchParams: () => ({
      get: (key: string) => (key === 'token' ? params.token : null),
    }),
  };
});

const mockConfirmEmailChange = vi.fn();
vi.mock('@/lib/api', () => ({
  api: { confirmEmailChange: (...args: unknown[]) => mockConfirmEmailChange(...args) },
}));

// Import AFTER mocks are set up
import { ConfirmEmailContent } from '../page';

describe('ConfirmEmailContent', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    params.token = 'validtoken123';
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows success state on valid token', async () => {
    mockConfirmEmailChange.mockResolvedValue({ status: 'ok', message: 'Email updated' });
    render(<ConfirmEmailContent />);

    await waitFor(() => {
      expect(screen.getByText('Email address updated!')).toBeInTheDocument();
    }, { timeout: 3000 });

    // Wait for the setTimeout(2000) to resolve
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/account');
    }, { timeout: 3000 });
  }, 8000);

  it('shows error state on expired token', async () => {
    mockConfirmEmailChange.mockRejectedValue(new Error('Confirmation link has expired'));
    render(<ConfirmEmailContent />);

    await waitFor(
      () => {
        expect(screen.getByText('Confirmation failed')).toBeInTheDocument();
        expect(screen.getByText('Confirmation link has expired')).toBeInTheDocument();
      },
      { timeout: 3000 }
    );
  }, 8000);

  it('shows error state when token missing from URL', async () => {
    params.token = null;
    render(<ConfirmEmailContent />);

    await waitFor(
      () => {
        expect(screen.getByText('No confirmation token provided.')).toBeInTheDocument();
      },
      { timeout: 3000 }
    );
  }, 8000);

  it('shows link back to account settings on error', async () => {
    mockConfirmEmailChange.mockRejectedValue(new Error('Invalid confirmation link'));
    render(<ConfirmEmailContent />);

    await waitFor(
      () => {
        expect(screen.getByText('Return to account settings')).toBeInTheDocument();
      },
      { timeout: 3000 }
    );
  }, 8000);
});
