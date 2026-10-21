import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import AdminUsersPage from '../page';

// Mock HelpContext
vi.mock('@/lib/help/HelpContext', () => ({
  useHelp: () => ({
    helpMode: false,
    onboardingActive: false,
    currentStep: 0,
    activeSpotId: null,
    toggleHelpMode: vi.fn(),
    registerSpot: vi.fn(() => vi.fn()),
    getSpotsForPage: vi.fn(() => []),
    startOnboarding: vi.fn(),
    nextStep: vi.fn(),
    prevStep: vi.fn(),
    skipOnboarding: vi.fn(),
    hasSeenPage: vi.fn(() => true),
  }),
}));

// Mock API
vi.mock('@/lib/api', () => ({
  api: {
    getAdminUsers: vi.fn(),
    createAdminUser: vi.fn(),
    updateAdminUser: vi.fn(),
    deleteAdminUser: vi.fn(),
  },
  AdminUser: undefined,
}));

import { api } from '@/lib/api';

const mockUsers = {
  items: [
    {
      id: 1,
      username: 'admin',
      is_active: true,
      role: 'admin',
      created_at: '2026-01-01T00:00:00Z',
      event_count: 3,
    },
    {
      id: 2,
      username: 'djbob',
      is_active: true,
      role: 'dj',
      created_at: '2026-01-15T00:00:00Z',
      event_count: 1,
    },
    {
      id: 3,
      username: 'pending_user',
      is_active: true,
      role: 'pending',
      created_at: '2026-02-01T00:00:00Z',
      event_count: 0,
    },
  ],
  total: 3,
  page: 1,
  limit: 20,
};

describe('AdminUsersPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getAdminUsers).mockResolvedValue(mockUsers);
  });

  it('renders page heading and create button', async () => {
    render(<AdminUsersPage />);

    expect(screen.getByText('User Management')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create User' })).toBeInTheDocument();
  });

  it('displays users in a table', async () => {
    render(<AdminUsersPage />);

    await waitFor(() => {
      // Username "admin" also appears as the role badge text, so use getAllByText
      expect(screen.getAllByText('admin').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('djbob')).toBeInTheDocument();
      expect(screen.getByText('pending_user')).toBeInTheDocument();
    });
  });

  it('renders table column headers', async () => {
    render(<AdminUsersPage />);

    await waitFor(() => {
      expect(screen.getByText('Username')).toBeInTheDocument();
      expect(screen.getByText('Role')).toBeInTheDocument();
      expect(screen.getByText('Status')).toBeInTheDocument();
      expect(screen.getByText('Events')).toBeInTheDocument();
      expect(screen.getByText('Created')).toBeInTheDocument();
      expect(screen.getByText('Actions')).toBeInTheDocument();
    });
  });

  it('renders role filter tabs', async () => {
    render(<AdminUsersPage />);

    expect(screen.getByRole('button', { name: 'All' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Admins' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'DJs' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Pending' })).toBeInTheDocument();
  });

  it('renders edit and delete buttons for each user', async () => {
    render(<AdminUsersPage />);

    await waitFor(() => {
      const editButtons = screen.getAllByRole('button', { name: 'Edit' });
      const deleteButtons = screen.getAllByRole('button', { name: 'Delete' });
      expect(editButtons).toHaveLength(3);
      expect(deleteButtons).toHaveLength(3);
    });
  });

  it('shows error when API fails', async () => {
    vi.mocked(api.getAdminUsers).mockRejectedValue(new Error('Network error'));

    render(<AdminUsersPage />);

    await waitFor(() => {
      expect(screen.getByText('Failed to load users')).toBeInTheDocument();
    });
  });

  it('calls getAdminUsers on mount', async () => {
    render(<AdminUsersPage />);

    await waitFor(() => {
      expect(api.getAdminUsers).toHaveBeenCalledWith(1, 20, undefined);
    });
  });

  it('opens create user modal and submits', async () => {
    vi.mocked(api.createAdminUser).mockResolvedValue({
      id: 4, username: 'newdj', role: 'dj', is_active: true, created_at: '2026-02-20', event_count: 0,
    });

    render(<AdminUsersPage />);
    await waitFor(() => {
      expect(screen.getByText('djbob')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Create User' }));

    // Modal should appear
    expect(screen.getByLabelText('Username')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'newdj' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password123' } });

    fireEvent.submit(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => {
      expect(api.createAdminUser).toHaveBeenCalledWith({
        username: 'newdj', password: 'password123', role: 'dj',
      });
    });
  });

  it('shows error when create user fails', async () => {
    vi.mocked(api.createAdminUser).mockRejectedValue(new Error('Username conflict'));

    render(<AdminUsersPage />);
    await waitFor(() => {
      expect(screen.getByText('djbob')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Create User' }));
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'dup' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password123' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => {
      expect(screen.getByText('Username conflict')).toBeInTheDocument();
    });
  });

  it('opens edit modal and saves changes', async () => {
    vi.mocked(api.updateAdminUser).mockResolvedValue({
      id: 2, username: 'djbob', role: 'admin', is_active: true, created_at: '2026-01-15', event_count: 1,
    });

    render(<AdminUsersPage />);
    await waitFor(() => {
      expect(screen.getByText('djbob')).toBeInTheDocument();
    });

    // Click edit on second user (djbob)
    const editButtons = screen.getAllByRole('button', { name: 'Edit' });
    fireEvent.click(editButtons[1]);

    expect(screen.getByText('Edit: djbob')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Role'), { target: { value: 'admin' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(api.updateAdminUser).toHaveBeenCalledWith(2, { role: 'admin' });
    });
  });

  it('does not open or submit the edit form for a user with an unknown role', async () => {
    // Regression pinned to baseline 57cfcdc6867f: API role strings must not be
    // asserted into an authorization-sensitive role union.
    vi.mocked(api.getAdminUsers).mockResolvedValue({
      ...mockUsers,
      items: [...mockUsers.items, {
        id: 4,
        username: 'future-role-user',
        is_active: true,
        role: 'owner',
        created_at: '2026-03-01T00:00:00Z',
        event_count: 0,
      }],
    });

    render(<AdminUsersPage />);
    await waitFor(() => expect(screen.getByText('future-role-user')).toBeInTheDocument());

    fireEvent.click(screen.getAllByRole('button', { name: 'Edit' })[3]);

    expect(screen.queryByText('Edit: future-role-user')).not.toBeInTheDocument();
    expect(screen.getByText('Cannot edit user with an unsupported role.')).toBeInTheDocument();
    expect(api.updateAdminUser).not.toHaveBeenCalled();
  });

  it('shows error when edit fails', async () => {
    vi.mocked(api.updateAdminUser).mockRejectedValue(new Error('Cannot demote last admin'));

    render(<AdminUsersPage />);
    await waitFor(() => {
      expect(screen.getByText('djbob')).toBeInTheDocument();
    });

    const editButtons = screen.getAllByRole('button', { name: 'Edit' });
    fireEvent.click(editButtons[0]); // edit admin user
    fireEvent.change(screen.getByLabelText('Role'), { target: { value: 'dj' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(screen.getByText('Cannot demote last admin')).toBeInTheDocument();
    });
  });

  it('deletes user with confirmation', async () => {
    vi.mocked(api.deleteAdminUser).mockResolvedValue(undefined);
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(<AdminUsersPage />);
    await waitFor(() => {
      expect(screen.getByText('djbob')).toBeInTheDocument();
    });

    const deleteButtons = screen.getAllByRole('button', { name: 'Delete' });
    fireEvent.click(deleteButtons[1]); // delete djbob

    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() => {
      expect(api.deleteAdminUser).toHaveBeenCalledWith(2);
    });
  });

  it('cancels delete when confirm is rejected', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);

    render(<AdminUsersPage />);
    await waitFor(() => {
      expect(screen.getByText('djbob')).toBeInTheDocument();
    });

    const deleteButtons = screen.getAllByRole('button', { name: 'Delete' });
    fireEvent.click(deleteButtons[1]);

    expect(api.deleteAdminUser).not.toHaveBeenCalled();
  });

  it('filters by role when tab is clicked', async () => {
    render(<AdminUsersPage />);
    await waitFor(() => {
      expect(screen.getByText('djbob')).toBeInTheDocument();
    });

    vi.mocked(api.getAdminUsers).mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Pending' }));

    await waitFor(() => {
      expect(api.getAdminUsers).toHaveBeenCalledWith(1, 20, 'pending');
    });
  });

  it('shows pagination when total > limit', async () => {
    vi.mocked(api.getAdminUsers).mockResolvedValue({
      items: mockUsers.items,
      total: 50,
      page: 1,
      limit: 20,
    });

    render(<AdminUsersPage />);
    await waitFor(() => {
      expect(screen.getByText('Page 1 of 3')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next' })).not.toBeDisabled();
  });

  it('navigates to next page', async () => {
    vi.mocked(api.getAdminUsers).mockResolvedValue({
      items: mockUsers.items,
      total: 50,
      page: 1,
      limit: 20,
    });

    render(<AdminUsersPage />);
    await waitFor(() => {
      expect(screen.getByText('Page 1 of 3')).toBeInTheDocument();
    });

    vi.mocked(api.getAdminUsers).mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    await waitFor(() => {
      expect(api.getAdminUsers).toHaveBeenCalledWith(2, 20, undefined);
    });
  });

  it('shows delete error', async () => {
    vi.mocked(api.deleteAdminUser).mockRejectedValue(new Error('Cannot delete last admin'));
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(<AdminUsersPage />);
    await waitFor(() => {
      expect(screen.getByText('djbob')).toBeInTheDocument();
    });

    const deleteButtons = screen.getAllByRole('button', { name: 'Delete' });
    fireEvent.click(deleteButtons[0]);

    await waitFor(() => {
      expect(screen.getByText('Cannot delete last admin')).toBeInTheDocument();
    });
  });
});
