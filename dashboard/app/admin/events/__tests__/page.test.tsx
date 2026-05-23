import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import AdminEventsPage from '../page';

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

vi.mock('@/lib/api', () => ({
  api: {
    getAdminEvents: vi.fn(),
    updateAdminEvent: vi.fn(),
    deleteAdminEvent: vi.fn(),
    bulkDeleteAdminEvents: vi.fn(),
  },
  AdminEvent: undefined,
}));

import { api } from '@/lib/api';

const futureDate = new Date(Date.now() + 86400000).toISOString();
const pastDate = new Date(Date.now() - 86400000).toISOString();

const mockEvents = {
  items: [
    {
      id: 1,
      code: 'FRI001',
      join_code: '100IRF',
      name: 'Friday Night',
      owner_username: 'dj1',
      owner_id: 1,
      request_count: 15,
      is_active: true,
      expires_at: futureDate,
      created_at: '2026-01-01T00:00:00Z',
    },
    {
      id: 2,
      code: 'SAT002',
      join_code: '200TAS',
      name: 'Saturday Bash',
      owner_username: 'dj2',
      owner_id: 2,
      request_count: 3,
      is_active: true,
      expires_at: pastDate,
      created_at: '2026-01-15T00:00:00Z',
    },
    {
      id: 3,
      code: 'SUN003',
      join_code: '300NUS',
      name: 'Sunday Chill',
      owner_username: 'dj1',
      owner_id: 1,
      request_count: 0,
      is_active: false,
      expires_at: pastDate,
      created_at: '2026-02-01T00:00:00Z',
    },
  ],
  total: 3,
  page: 1,
  limit: 20,
};

describe('AdminEventsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getAdminEvents).mockResolvedValue(mockEvents);
  });

  it('renders page heading', async () => {
    render(<AdminEventsPage />);
    expect(screen.getByText('Event Management')).toBeInTheDocument();
  });

  it('displays events in table', async () => {
    render(<AdminEventsPage />);

    await waitFor(() => {
      expect(screen.getByText('Friday Night')).toBeInTheDocument();
      expect(screen.getByText('Saturday Bash')).toBeInTheDocument();
      expect(screen.getByText('Sunday Chill')).toBeInTheDocument();
    });
  });

  it('renders table columns', async () => {
    render(<AdminEventsPage />);

    await waitFor(() => {
      expect(screen.getByText('Code')).toBeInTheDocument();
      expect(screen.getByText('Name')).toBeInTheDocument();
      expect(screen.getByText('Owner')).toBeInTheDocument();
      expect(screen.getByText('Requests')).toBeInTheDocument();
      expect(screen.getByText('Status')).toBeInTheDocument();
    });
  });

  it('shows Active, Expired, and Inactive status badges', async () => {
    render(<AdminEventsPage />);

    await waitFor(() => {
      expect(screen.getByText('Active')).toBeInTheDocument();
      expect(screen.getByText('Expired')).toBeInTheDocument();
      expect(screen.getByText('Inactive')).toBeInTheDocument();
    });
  });

  it('shows error when API fails', async () => {
    vi.mocked(api.getAdminEvents).mockRejectedValue(new Error('Network error'));

    render(<AdminEventsPage />);

    await waitFor(() => {
      expect(screen.getByText('Failed to load events')).toBeInTheDocument();
    });
  });

  it('opens edit modal and saves', async () => {
    vi.mocked(api.updateAdminEvent).mockResolvedValue({
      ...mockEvents.items[0],
      name: 'Updated Name',
    });

    render(<AdminEventsPage />);
    await waitFor(() => {
      expect(screen.getByText('Friday Night')).toBeInTheDocument();
    });

    const editButtons = screen.getAllByRole('button', { name: 'Edit' });
    fireEvent.click(editButtons[0]);

    expect(screen.getByText('Edit: FRI001')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Event Name'), {
      target: { value: 'Updated Name' },
    });
    fireEvent.submit(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(api.updateAdminEvent).toHaveBeenCalledWith('FRI001', { name: 'Updated Name' });
    });
  });

  it('shows error when edit fails', async () => {
    vi.mocked(api.updateAdminEvent).mockRejectedValue(new Error('Permission denied'));

    render(<AdminEventsPage />);
    await waitFor(() => {
      expect(screen.getByText('Friday Night')).toBeInTheDocument();
    });

    const editButtons = screen.getAllByRole('button', { name: 'Edit' });
    fireEvent.click(editButtons[0]);
    fireEvent.submit(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(screen.getByText('Permission denied')).toBeInTheDocument();
    });
  });

  it('deletes event with confirmation', async () => {
    vi.mocked(api.deleteAdminEvent).mockResolvedValue(undefined);
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(<AdminEventsPage />);
    await waitFor(() => {
      expect(screen.getByText('Friday Night')).toBeInTheDocument();
    });

    const deleteButtons = screen.getAllByRole('button', { name: 'Delete' });
    fireEvent.click(deleteButtons[0]);

    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() => {
      expect(api.deleteAdminEvent).toHaveBeenCalledWith('FRI001');
    });
  });

  it('cancels delete on rejected confirm', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);

    render(<AdminEventsPage />);
    await waitFor(() => {
      expect(screen.getByText('Friday Night')).toBeInTheDocument();
    });

    const deleteButtons = screen.getAllByRole('button', { name: 'Delete' });
    fireEvent.click(deleteButtons[0]);

    expect(api.deleteAdminEvent).not.toHaveBeenCalled();
  });

  it('shows pagination when total > limit', async () => {
    vi.mocked(api.getAdminEvents).mockResolvedValue({
      items: mockEvents.items,
      total: 50,
      page: 1,
      limit: 20,
    });

    render(<AdminEventsPage />);
    await waitFor(() => {
      expect(screen.getByText('Page 1 of 3')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
  });

  it('navigates to next page', async () => {
    vi.mocked(api.getAdminEvents).mockResolvedValue({
      items: mockEvents.items,
      total: 50,
      page: 1,
      limit: 20,
    });

    render(<AdminEventsPage />);
    await waitFor(() => {
      expect(screen.getByText('Page 1 of 3')).toBeInTheDocument();
    });

    vi.mocked(api.getAdminEvents).mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    await waitFor(() => {
      expect(api.getAdminEvents).toHaveBeenCalledWith(2, 20);
    });
  });

  it('cancels edit modal', async () => {
    render(<AdminEventsPage />);
    await waitFor(() => {
      expect(screen.getByText('Friday Night')).toBeInTheDocument();
    });

    const editButtons = screen.getAllByRole('button', { name: 'Edit' });
    fireEvent.click(editButtons[0]);
    expect(screen.getByText('Edit: FRI001')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByText('Edit: FRI001')).not.toBeInTheDocument();
  });

  it('shows delete error', async () => {
    vi.mocked(api.deleteAdminEvent).mockRejectedValue(new Error('Cannot delete'));
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(<AdminEventsPage />);
    await waitFor(() => {
      expect(screen.getByText('Friday Night')).toBeInTheDocument();
    });

    const deleteButtons = screen.getAllByRole('button', { name: 'Delete' });
    fireEvent.click(deleteButtons[0]);

    await waitFor(() => {
      expect(screen.getByText('Cannot delete')).toBeInTheDocument();
    });
  });

  describe('Batch delete (selection mode)', () => {
    it('renders Advanced checkbox', async () => {
      render(<AdminEventsPage />);
      await waitFor(() => expect(screen.getByText('Friday Night')).toBeInTheDocument());
      expect(screen.getByLabelText('Advanced')).toBeInTheDocument();
    });

    it('toggles selection mode with checkbox column', async () => {
      render(<AdminEventsPage />);
      await waitFor(() => expect(screen.getByText('Friday Night')).toBeInTheDocument());

      expect(screen.queryByLabelText('Select All')).not.toBeInTheDocument();

      fireEvent.click(screen.getByLabelText('Advanced'));
      expect(screen.getByLabelText('Select All')).toBeInTheDocument();
    });

    it('select all header checkbox', async () => {
      render(<AdminEventsPage />);
      await waitFor(() => expect(screen.getByText('Friday Night')).toBeInTheDocument());

      fireEvent.click(screen.getByLabelText('Advanced'));

      const selectAll = screen.getByLabelText('Select All');
      fireEvent.click(selectAll);
      expect(screen.getByText('Delete Selected (3)')).toBeInTheDocument();

      fireEvent.click(selectAll);
      expect(screen.queryByText(/Delete Selected/)).not.toBeInTheDocument();
    });

    it('delete selected calls bulkDeleteAdminEvents', async () => {
      vi.mocked(api.bulkDeleteAdminEvents).mockResolvedValue({ status: 'ok', count: 2 });
      vi.spyOn(window, 'confirm').mockReturnValue(true);

      render(<AdminEventsPage />);
      await waitFor(() => expect(screen.getByText('Friday Night')).toBeInTheDocument());

      fireEvent.click(screen.getByLabelText('Advanced'));

      const checkboxes = screen.getAllByRole('checkbox', { name: /Select event/ });
      fireEvent.click(checkboxes[0]);
      fireEvent.click(checkboxes[1]);

      await act(async () => {
        fireEvent.click(screen.getByText('Delete Selected (2)'));
      });

      expect(window.confirm).toHaveBeenCalled();
      expect(api.bulkDeleteAdminEvents).toHaveBeenCalledWith(['FRI001', 'SAT002']);
    });
  });
});
