import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockPush = vi.fn();
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

import { ConfirmEmailContent } from '../ConfirmEmailContent';

describe('ConfirmEmailContent', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    params.token = 'validtoken123';
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows success for a valid token and redirects to account settings', async () => {
    mockConfirmEmailChange.mockResolvedValue({ status: 'ok', message: 'Email updated' });
    render(<ConfirmEmailContent />);

    await waitFor(() => {
      expect(screen.getByText('Email address updated!')).toBeInTheDocument();
    }, { timeout: 3000 });
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/account');
    }, { timeout: 3000 });
  }, 8000);

  it('shows the expired-token error', async () => {
    mockConfirmEmailChange.mockRejectedValue(new Error('Confirmation link has expired'));
    render(<ConfirmEmailContent />);

    await waitFor(() => {
      expect(screen.getByText('Confirmation failed')).toBeInTheDocument();
      expect(screen.getByText('Confirmation link has expired')).toBeInTheDocument();
    }, { timeout: 3000 });
  }, 8000);

  it('shows the missing-token error without calling the API', async () => {
    params.token = null;
    render(<ConfirmEmailContent />);

    await waitFor(() => {
      expect(screen.getByText('No confirmation token provided.')).toBeInTheDocument();
    }, { timeout: 3000 });
    expect(mockConfirmEmailChange).not.toHaveBeenCalled();
  }, 8000);

  it('provides an account settings link after confirmation fails', async () => {
    mockConfirmEmailChange.mockRejectedValue(new Error('Invalid confirmation link'));
    render(<ConfirmEmailContent />);

    expect(await screen.findByText('Return to account settings')).toHaveAttribute('href', '/account');
  }, 8000);
});
