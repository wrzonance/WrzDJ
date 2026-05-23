import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import DashboardPage from '../page';

const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock('@/lib/help/HelpContext', () => ({
  useHelp: () => ({
    helpMode: false, onboardingActive: false, currentStep: 0, activeSpotId: null,
    toggleHelpMode: vi.fn(), registerSpot: vi.fn(() => vi.fn()),
    getSpotsForPage: vi.fn(() => []), startOnboarding: vi.fn(),
    nextStep: vi.fn(), prevStep: vi.fn(), skipOnboarding: vi.fn(),
    hasSeenPage: vi.fn(() => true),
  }),
}));

vi.mock('@/components/help/HelpSpot', () => ({
  HelpSpot: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('@/components/help/HelpButton', () => ({
  HelpButton: () => null,
}));
vi.mock('@/components/help/OnboardingOverlay', () => ({
  OnboardingOverlay: () => null,
}));

vi.mock('../components/ActivityLogPanel', () => ({
  ActivityLogPanel: () => <div data-testid="activity-log-panel" />,
}));

let mockRole = 'dj';
let mockIsAuthenticated = true;
let mockIsLoading = false;
const mockLogout = vi.fn();
vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    isAuthenticated: mockIsAuthenticated,
    isLoading: mockIsLoading,
    role: mockRole,
    logout: mockLogout,
  }),
}));

vi.mock('@/lib/api', () => ({
  api: {
    getEvents: vi.fn(),
    createEvent: vi.fn(),
    bulkDeleteEvents: vi.fn(),
    getTidalStatus: vi.fn(),
    getBeatportStatus: vi.fn(),
    getActivityLog: vi.fn(),
    patchCollectionSettings: vi.fn(),
  },
  Event: undefined,
}));

import { api } from '@/lib/api';

function mockEvent(overrides = {}) {
  return {
    id: 1,
    code: 'EVT01',
      join_code: '10TVEJ',
      collect_url: null,
    name: 'Friday Night',
    created_at: '2026-01-01T00:00:00Z',
    expires_at: '2026-01-02T00:00:00Z',
    is_active: true,
    join_url: null,
    tidal_sync_enabled: false,
    tidal_playlist_id: null,
    beatport_sync_enabled: false,
    beatport_playlist_id: null,
    banner_url: null,
    banner_kiosk_url: null,
    banner_colors: null,
    requests_open: true,
    collection_opens_at: null,
    live_starts_at: null,
    submission_cap_per_guest: 15,
    collection_phase_override: null,
    archived_at: null,
    request_count: null,
    status: null,
    ...overrides,
  };
}

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRole = 'dj';
    mockIsAuthenticated = true;
    mockIsLoading = false;
    vi.mocked(api.getTidalStatus).mockResolvedValue(null as never);
    vi.mocked(api.getBeatportStatus).mockResolvedValue(null as never);
    vi.mocked(api.getActivityLog).mockResolvedValue([]);
  });

  it('renders page heading and create button', async () => {
    vi.mocked(api.getEvents).mockResolvedValue([]);
    render(<DashboardPage />);
    expect(screen.getByText('Dashboard')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create Event' })).toBeInTheDocument();
  });

  it('renders Account button linking to /account', async () => {
    vi.mocked(api.getEvents).mockResolvedValue([]);
    render(<DashboardPage />);
    expect(screen.getByRole('link', { name: 'Account' })).toHaveAttribute('href', '/account');
  });

  it('renders activity log panel', async () => {
    vi.mocked(api.getEvents).mockResolvedValue([]);
    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId('activity-log-panel')).toBeInTheDocument();
    });
  });

  it('renders cloud providers section', async () => {
    vi.mocked(api.getEvents).mockResolvedValue([]);
    vi.mocked(api.getTidalStatus).mockResolvedValue({ linked: true } as never);
    vi.mocked(api.getBeatportStatus).mockResolvedValue({ linked: false } as never);
    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getByText('Tidal')).toBeInTheDocument();
      expect(screen.getByText('Beatport')).toBeInTheDocument();
    });
  });

  it('shows empty state when no events exist', async () => {
    vi.mocked(api.getEvents).mockResolvedValue([]);
    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getByText(/No events yet/)).toBeInTheDocument();
    });
  });

  it('displays events when loaded', async () => {
    vi.mocked(api.getEvents).mockResolvedValue([mockEvent()]);
    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getByText('Friday Night')).toBeInTheDocument();
      expect(screen.getByText('EVT01')).toBeInTheDocument();
    });
  });

  it('shows error message when events API fails', async () => {
    vi.mocked(api.getEvents).mockRejectedValue(new Error('Network error'));
    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getByText('Failed to load dashboard data')).toBeInTheDocument();
    });
  });

  it('shows logout button', async () => {
    vi.mocked(api.getEvents).mockResolvedValue([]);
    render(<DashboardPage />);
    expect(screen.getByRole('button', { name: 'Logout' })).toBeInTheDocument();
  });

  it('shows inactive badge for inactive events', async () => {
    vi.mocked(api.getEvents).mockResolvedValue([mockEvent({ is_active: false })]);
    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getByText('Inactive')).toBeInTheDocument();
    });
  });

  describe('Loading & auth redirects', () => {
    it('shows Loading while auth is resolving', () => {
      mockIsLoading = true;
      mockIsAuthenticated = false;
      vi.mocked(api.getEvents).mockResolvedValue([]);
      render(<DashboardPage />);
      expect(screen.getByText('Loading...')).toBeInTheDocument();
    });

    it('shows "Loading events..." during fetch', async () => {
      let resolveEvents!: (v: never[]) => void;
      vi.mocked(api.getEvents).mockImplementation(
        () => new Promise((r) => { resolveEvents = r; }),
      );
      render(<DashboardPage />);
      expect(screen.getByText('Loading events...')).toBeInTheDocument();
      await act(async () => { resolveEvents([]); });
    });

    it('redirects unauthenticated users to /login', () => {
      mockIsAuthenticated = false;
      mockIsLoading = false;
      vi.mocked(api.getEvents).mockResolvedValue([]);
      render(<DashboardPage />);
      expect(mockPush).toHaveBeenCalledWith('/login');
    });

    it('redirects pending users to /pending', () => {
      mockRole = 'pending';
      vi.mocked(api.getEvents).mockResolvedValue([]);
      render(<DashboardPage />);
      expect(mockPush).toHaveBeenCalledWith('/pending');
    });
  });

  describe('Create event form', () => {
    it('shows form when Create Event clicked', async () => {
      vi.mocked(api.getEvents).mockResolvedValue([]);
      render(<DashboardPage />);
      fireEvent.click(screen.getByRole('button', { name: 'Create Event' }));
      expect(screen.getByLabelText('Event Name')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Create' })).toBeInTheDocument();
    });

    it('creates event and adds to list', async () => {
      vi.mocked(api.getEvents).mockResolvedValue([]);
      const newEvent = mockEvent({ id: 2, code: 'NEW01',
      join_code: '10WENJ',
      collect_url: null, name: 'New Party' });
      vi.mocked(api.createEvent).mockResolvedValue(newEvent);
      render(<DashboardPage />);
      await waitFor(() => expect(screen.getByText(/No events yet/)).toBeInTheDocument());
      fireEvent.click(screen.getByRole('button', { name: 'Create Event' }));
      fireEvent.change(screen.getByLabelText('Event Name'), { target: { value: 'New Party' } });
      await act(async () => {
        fireEvent.submit(screen.getByRole('button', { name: 'Create' }));
      });
      expect(api.createEvent).toHaveBeenCalledWith('New Party');
      await waitFor(() => {
        expect(screen.getByText('New Party')).toBeInTheDocument();
      });
    });

    it('hides form and resets input after create', async () => {
      vi.mocked(api.getEvents).mockResolvedValue([]);
      vi.mocked(api.createEvent).mockResolvedValue(mockEvent());
      render(<DashboardPage />);
      await waitFor(() => expect(screen.getByText(/No events yet/)).toBeInTheDocument());
      fireEvent.click(screen.getByRole('button', { name: 'Create Event' }));
      fireEvent.change(screen.getByLabelText('Event Name'), { target: { value: 'Test' } });
      await act(async () => {
        fireEvent.submit(screen.getByRole('button', { name: 'Create' }));
      });
      await waitFor(() => {
        expect(screen.queryByLabelText('Event Name')).not.toBeInTheDocument();
      });
    });

    it('shows error when create fails', async () => {
      vi.mocked(api.getEvents).mockResolvedValue([]);
      vi.mocked(api.createEvent).mockRejectedValue(new Error('Name taken'));
      render(<DashboardPage />);
      await waitFor(() => expect(screen.getByText(/No events yet/)).toBeInTheDocument());
      fireEvent.click(screen.getByRole('button', { name: 'Create Event' }));
      fireEvent.change(screen.getByLabelText('Event Name'), { target: { value: 'Dup' } });
      await act(async () => {
        fireEvent.submit(screen.getByRole('button', { name: 'Create' }));
      });
      await waitFor(() => {
        expect(screen.getByText('Name taken')).toBeInTheDocument();
      });
    });

    it('hides form on Cancel', async () => {
      vi.mocked(api.getEvents).mockResolvedValue([]);
      render(<DashboardPage />);
      await waitFor(() => expect(screen.getByText(/No events yet/)).toBeInTheDocument());
      fireEvent.click(screen.getByRole('button', { name: 'Create Event' }));
      expect(screen.getByLabelText('Event Name')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
      expect(screen.queryByLabelText('Event Name')).not.toBeInTheDocument();
      expect(api.createEvent).not.toHaveBeenCalled();
    });
  });

  describe('Logout', () => {
    it('calls logout on Logout click', async () => {
      vi.mocked(api.getEvents).mockResolvedValue([]);
      render(<DashboardPage />);
      fireEvent.click(screen.getByRole('button', { name: 'Logout' }));
      expect(mockLogout).toHaveBeenCalledOnce();
    });
  });

  describe('Admin role', () => {
    it('shows Admin button for admin role', async () => {
      mockRole = 'admin';
      vi.mocked(api.getEvents).mockResolvedValue([]);
      render(<DashboardPage />);
      expect(screen.getByRole('button', { name: 'Admin' })).toBeInTheDocument();
    });

    it('hides Admin button for dj role', async () => {
      mockRole = 'dj';
      vi.mocked(api.getEvents).mockResolvedValue([]);
      render(<DashboardPage />);
      expect(screen.queryByRole('button', { name: 'Admin' })).not.toBeInTheDocument();
    });
  });

  describe('Batch delete (selection mode)', () => {
    const twoEvents = [
      mockEvent({ id: 1, code: 'EVT01',
      join_code: '10TVEJ',
      collect_url: null, name: 'Friday Night' }),
      mockEvent({ id: 2, code: 'EVT02',
      join_code: '20TVEJ',
      collect_url: null, name: 'Saturday Bash' }),
    ];

    it('renders Advanced checkbox', async () => {
      vi.mocked(api.getEvents).mockResolvedValue(twoEvents);
      render(<DashboardPage />);
      await waitFor(() => expect(screen.getByText('Friday Night')).toBeInTheDocument());
      expect(screen.getByLabelText('Advanced')).toBeInTheDocument();
    });

    it('toggles selection mode', async () => {
      vi.mocked(api.getEvents).mockResolvedValue(twoEvents);
      render(<DashboardPage />);
      await waitFor(() => expect(screen.getByText('Friday Night')).toBeInTheDocument());
      expect(screen.queryByRole('button', { name: /Delete Selected/ })).not.toBeInTheDocument();
      fireEvent.click(screen.getByLabelText('Advanced'));
      expect(screen.getByLabelText('Select All')).toBeInTheDocument();
    });

    it('calls bulkDeleteEvents and re-fetches on confirm', async () => {
      vi.mocked(api.getEvents)
        .mockResolvedValueOnce(twoEvents)
        .mockResolvedValueOnce([twoEvents[1]]);
      vi.mocked(api.bulkDeleteEvents).mockResolvedValue({ status: 'ok', count: 1 });
      vi.spyOn(window, 'confirm').mockReturnValue(true);
      render(<DashboardPage />);
      await waitFor(() => expect(screen.getByText('Friday Night')).toBeInTheDocument());
      fireEvent.click(screen.getByLabelText('Advanced'));
      const checkboxes = screen.getAllByRole('checkbox', { name: /Select event/ });
      fireEvent.click(checkboxes[0]);
      await act(async () => {
        fireEvent.click(screen.getByText('Delete Selected (1)'));
      });
      expect(api.bulkDeleteEvents).toHaveBeenCalledWith(['EVT01']);
      expect(api.getEvents).toHaveBeenCalledTimes(2);
    });

    it('clears selection after delete', async () => {
      vi.mocked(api.getEvents)
        .mockResolvedValueOnce(twoEvents)
        .mockResolvedValueOnce([twoEvents[1]]);
      vi.mocked(api.bulkDeleteEvents).mockResolvedValue({ status: 'ok', count: 1 });
      vi.spyOn(window, 'confirm').mockReturnValue(true);
      render(<DashboardPage />);
      await waitFor(() => expect(screen.getByText('Friday Night')).toBeInTheDocument());
      fireEvent.click(screen.getByLabelText('Advanced'));
      const checkboxes = screen.getAllByRole('checkbox', { name: /Select event/ });
      fireEvent.click(checkboxes[0]);
      await act(async () => {
        fireEvent.click(screen.getByText('Delete Selected (1)'));
      });
      await waitFor(() => {
        expect(screen.queryByText(/Delete Selected/)).not.toBeInTheDocument();
      });
    });

    it('shows error when bulk delete fails', async () => {
      vi.mocked(api.getEvents).mockResolvedValue(twoEvents);
      vi.mocked(api.bulkDeleteEvents).mockRejectedValue(new Error('Server error'));
      vi.spyOn(window, 'confirm').mockReturnValue(true);
      render(<DashboardPage />);
      await waitFor(() => expect(screen.getByText('Friday Night')).toBeInTheDocument());
      fireEvent.click(screen.getByLabelText('Advanced'));
      const checkboxes = screen.getAllByRole('checkbox', { name: /Select event/ });
      fireEvent.click(checkboxes[0]);
      await act(async () => {
        fireEvent.click(screen.getByText('Delete Selected (1)'));
      });
      await waitFor(() => {
        expect(screen.getByText('Server error')).toBeInTheDocument();
      });
    });

    it('shows fallback error when bulk delete throws non-Error', async () => {
      vi.mocked(api.getEvents).mockResolvedValue(twoEvents);
      vi.mocked(api.bulkDeleteEvents).mockRejectedValue('unexpected');
      vi.spyOn(window, 'confirm').mockReturnValue(true);
      render(<DashboardPage />);
      await waitFor(() => expect(screen.getByText('Friday Night')).toBeInTheDocument());
      fireEvent.click(screen.getByLabelText('Advanced'));
      const checkboxes = screen.getAllByRole('checkbox', { name: /Select event/ });
      fireEvent.click(checkboxes[0]);
      await act(async () => {
        fireEvent.click(screen.getByText('Delete Selected (1)'));
      });
      await waitFor(() => {
        expect(screen.getByText('Failed to delete events')).toBeInTheDocument();
      });
    });

    it('deselects event when clicked again in selection mode', async () => {
      vi.mocked(api.getEvents).mockResolvedValue(twoEvents);
      render(<DashboardPage />);
      await waitFor(() => expect(screen.getByText('Friday Night')).toBeInTheDocument());
      fireEvent.click(screen.getByLabelText('Advanced'));
      const checkboxes = screen.getAllByRole('checkbox', { name: /Select event/ });
      fireEvent.click(checkboxes[0]);
      expect(screen.getByText('Delete Selected (1)')).toBeInTheDocument();
      fireEvent.click(checkboxes[0]);
      expect(screen.queryByText(/Delete Selected/)).not.toBeInTheDocument();
    });
  });

  describe('Secondary API failures', () => {
    it('renders page when tidal/beatport/log APIs fail', async () => {
      vi.mocked(api.getEvents).mockResolvedValue([]);
      vi.mocked(api.getTidalStatus).mockRejectedValue(new Error('Tidal down'));
      vi.mocked(api.getBeatportStatus).mockRejectedValue(new Error('Beatport down'));
      vi.mocked(api.getActivityLog).mockRejectedValue(new Error('Log down'));
      render(<DashboardPage />);
      await waitFor(() => {
        expect(screen.getByText(/No events yet/)).toBeInTheDocument();
      });
      expect(screen.getByText('Tidal')).toBeInTheDocument();
      expect(screen.getByText('Beatport')).toBeInTheDocument();
    });
  });
});
