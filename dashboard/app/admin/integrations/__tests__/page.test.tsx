import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import AdminIntegrationsPage from '../page';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => '/admin/integrations',
}));

vi.mock('@/components/PageControls', () => ({
  PageControls: ({ children }: { children?: React.ReactNode }) => <div data-testid="page-controls">{children}</div>,
}));

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

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isLoading: false,
    role: 'admin',
    logout: vi.fn(),
  }),
}));

const mockGetIntegrations = vi.fn();
const mockToggleIntegration = vi.fn();
const mockCheckIntegrationHealth = vi.fn();

vi.mock('@/lib/api', () => ({
  api: {
    getIntegrations: (...args: unknown[]) => mockGetIntegrations(...args),
    toggleIntegration: (...args: unknown[]) => mockToggleIntegration(...args),
    checkIntegrationHealth: (...args: unknown[]) =>
      mockCheckIntegrationHealth(...args),
  },
}));

const mockServices = {
  services: [
    {
      service: 'spotify',
      display_name: 'Spotify',
      enabled: true,
      configured: true,
      capabilities: {
        auth: 'configured' as const,
        catalog_search: 'configured' as const,
        playlist_sync: 'not_implemented' as const,
      },
      last_check_error: null,
    },
    {
      service: 'tidal',
      display_name: 'Tidal',
      enabled: true,
      configured: true,
      capabilities: {
        auth: 'configured' as const,
        catalog_search: 'configured' as const,
        playlist_sync: 'configured' as const,
      },
      last_check_error: null,
    },
    {
      service: 'beatport',
      display_name: 'Beatport',
      enabled: false,
      configured: false,
      capabilities: {
        auth: 'not_configured' as const,
        catalog_search: 'not_configured' as const,
        playlist_sync: 'not_configured' as const,
      },
      last_check_error: null,
    },
    {
      service: 'bridge',
      display_name: 'Bridge (DJ Equipment)',
      enabled: true,
      configured: true,
      capabilities: {
        auth: 'configured' as const,
        catalog_search: 'not_implemented' as const,
        playlist_sync: 'not_implemented' as const,
      },
      last_check_error: null,
    },
  ],
};

describe('AdminIntegrationsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetIntegrations.mockResolvedValue(mockServices);
  });

  it('renders all four services', async () => {
    render(<AdminIntegrationsPage />);
    await waitFor(() => {
      expect(screen.getByText('Spotify')).toBeDefined();
      expect(screen.getByText('Tidal')).toBeDefined();
      expect(screen.getByText('Beatport')).toBeDefined();
      expect(screen.getByText('Bridge (DJ Equipment)')).toBeDefined();
    });
    expect(screen.getByTestId('page-controls')).toBeInTheDocument();
  });

  it('shows loading state initially', () => {
    mockGetIntegrations.mockReturnValue(new Promise(() => {}));
    render(<AdminIntegrationsPage />);
    expect(screen.getByText('Loading integrations...')).toBeDefined();
  });

  it('shows error on fetch failure', async () => {
    mockGetIntegrations.mockRejectedValue(new Error('Network error'));
    render(<AdminIntegrationsPage />);
    await waitFor(() => {
      expect(
        screen.getByText('Failed to load integration status')
      ).toBeDefined();
    });
  });

  it('renders capability badges', async () => {
    render(<AdminIntegrationsPage />);
    await waitFor(() => {
      const naBadges = screen.getAllByText('N/A');
      expect(naBadges.length).toBeGreaterThan(0);
    });
  });

  it('renders check health buttons for each service', async () => {
    render(<AdminIntegrationsPage />);
    await waitFor(() => {
      const checkButtons = screen.getAllByText('Check Health');
      expect(checkButtons).toHaveLength(4);
    });
  });

  it('calls toggleIntegration when toggle is clicked', async () => {
    mockToggleIntegration.mockResolvedValue({
      service: 'spotify',
      enabled: false,
    });

    render(<AdminIntegrationsPage />);

    await waitFor(() => {
      expect(screen.getByText('Spotify')).toBeDefined();
    });

    const toggles = screen.getAllByRole('button', { name: /disable|enable/i });
    fireEvent.click(toggles[0]);

    await waitFor(() => {
      expect(mockToggleIntegration).toHaveBeenCalledWith('spotify', false);
    });
  });

  it('calls checkIntegrationHealth when check button is clicked', async () => {
    mockCheckIntegrationHealth.mockResolvedValue({
      service: 'spotify',
      healthy: true,
      capabilities: {
        auth: 'yes',
        catalog_search: 'yes',
        playlist_sync: 'not_implemented',
      },
      error: null,
    });

    render(<AdminIntegrationsPage />);

    await waitFor(() => {
      expect(screen.getByText('Spotify')).toBeDefined();
    });

    const checkButtons = screen.getAllByText('Check Health');
    fireEvent.click(checkButtons[0]);

    await waitFor(() => {
      expect(mockCheckIntegrationHealth).toHaveBeenCalledWith('spotify');
    });
  });

  it('renders badge legend', async () => {
    render(<AdminIntegrationsPage />);
    await waitFor(() => {
      expect(screen.getByText('Badge Legend')).toBeDefined();
      expect(screen.getByText('Working')).toBeDefined();
      expect(screen.getByText('Check failed')).toBeDefined();
    });
  });

  it('shows page title and description', async () => {
    render(<AdminIntegrationsPage />);
    await waitFor(() => {
      expect(screen.getByText('Integrations')).toBeDefined();
    });
  });
});
