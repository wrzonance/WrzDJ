import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import AccountPage from '../page';

const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ isAuthenticated: true, isLoading: false }),
}));

const mockChangePassword = vi.fn();
const mockRequestEmailChange = vi.fn();
const mockGetMe = vi.fn();

vi.mock('@/lib/api', () => ({
  api: {
    getMe: () => mockGetMe(),
    changePassword: (...args: unknown[]) => mockChangePassword(...args),
    requestEmailChange: (...args: unknown[]) => mockRequestEmailChange(...args),
    // The AI providers section (relocated from /settings/ai, #357) mounts
    // inside the account page. Stub its API surface so the section can render
    // without network access. getLlmPolicy rejects → fail-closed (no extra UI).
    listLlmConnectors: () => Promise.resolve([]),
    getLlmPolicy: () => Promise.reject(new Error('forbidden')),
  },
}));

describe('AccountPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetMe.mockResolvedValue({
      id: 1,
      username: 'testuser',
      role: 'dj',
      help_pages_seen: [],
      pending_email: null,
      email: null,
    });
  });

  it('renders Change Password and Change Email headings', async () => {
    render(<AccountPage />);
    await waitFor(() => {
      expect(screen.getByText('Change Password')).toBeInTheDocument();
      expect(screen.getByText('Change Email')).toBeInTheDocument();
    });
  });

  it('renders the relocated AI / Model providers section', async () => {
    render(<AccountPage />);
    await waitFor(() => {
      expect(screen.getByText('AI / Model providers')).toBeInTheDocument();
    });
  });

  it('submits password change with correct payload', async () => {
    mockChangePassword.mockResolvedValue({ status: 'ok', message: 'Updated' });
    render(<AccountPage />);

    await waitFor(() => screen.getByLabelText('Current Password'));

    fireEvent.change(screen.getByLabelText('Current Password'), {
      target: { value: 'oldpass' },
    });
    fireEvent.change(screen.getByLabelText('New Password'), {
      target: { value: 'newpass123' },
    });
    fireEvent.change(screen.getByLabelText('Confirm New Password'), {
      target: { value: 'newpass123' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Update Password' }));

    await waitFor(() => {
      expect(mockChangePassword).toHaveBeenCalledWith({
        current_password: 'oldpass',
        new_password: 'newpass123',
        confirm_new_password: 'newpass123',
      });
    });
  });

  it('redirects to /login after successful password change', async () => {
    mockChangePassword.mockResolvedValue({ status: 'ok', message: 'Updated' });
    render(<AccountPage />);

    await waitFor(() => screen.getByLabelText('Current Password'));
    fireEvent.change(screen.getByLabelText('Current Password'), { target: { value: 'oldpass' } });
    fireEvent.change(screen.getByLabelText('New Password'), { target: { value: 'newpass123' } });
    fireEvent.change(screen.getByLabelText('Confirm New Password'), {
      target: { value: 'newpass123' },
    });

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole('button', { name: 'Update Password' }));

    // Let the async password change resolve, then advance the redirect timer
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(mockPush).toHaveBeenCalledWith('/login');
    vi.useRealTimers();
  });

  it('shows error when passwords do not match', async () => {
    render(<AccountPage />);
    await waitFor(() => screen.getByLabelText('New Password'));

    fireEvent.change(screen.getByLabelText('New Password'), { target: { value: 'newpass123' } });
    fireEvent.change(screen.getByLabelText('Confirm New Password'), {
      target: { value: 'different' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Update Password' }));

    expect(screen.getByText('New passwords do not match')).toBeInTheDocument();
    expect(mockChangePassword).not.toHaveBeenCalled();
  });

  it('shows check-inbox state after successful email request', async () => {
    mockRequestEmailChange.mockResolvedValue({ status: 'ok', message: 'Sent' });
    render(<AccountPage />);

    await waitFor(() => screen.getByLabelText('New Email Address'));
    fireEvent.change(screen.getByLabelText('New Email Address'), {
      target: { value: 'new@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send Confirmation' }));

    await waitFor(() => {
      expect(screen.getByText('new@example.com')).toBeInTheDocument();
      expect(screen.getByText(/Check your inbox/)).toBeInTheDocument();
    });
  });

  it('shows pending email from getMe on load', async () => {
    mockGetMe.mockResolvedValue({
      id: 1,
      username: 'testuser',
      role: 'dj',
      help_pages_seen: [],
      pending_email: 'pending@example.com',
      email: null,
    });
    render(<AccountPage />);
    await waitFor(() => {
      expect(screen.getByText('pending@example.com')).toBeInTheDocument();
    });
  });
});
