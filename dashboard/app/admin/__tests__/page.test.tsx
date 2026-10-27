import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import AdminOverviewPage from '../page';

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
    dismissOnboarding: vi.fn(),
    hasSeenPage: vi.fn(() => true),
  }),
}));

vi.mock('@/lib/api', () => ({
  api: {
    getAdminStats: vi.fn(),
  },
}));

import { api } from '@/lib/api';

const mockStats = {
  total_users: 5,
  active_users: 4,
  pending_users: 1,
  total_events: 7,
  active_events: 2,
  total_requests: 99,
};

describe('AdminOverviewPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getAdminStats).mockResolvedValue(mockStats);
  });

  it('mounts the page controls once stats have loaded', async () => {
    render(<AdminOverviewPage />);

    await waitFor(() => {
      expect(screen.getByText('Dashboard Overview')).toBeInTheDocument();
    });
    expect(screen.getByTestId('page-controls')).toBeInTheDocument();
  });

  it('keeps the page controls available while stats are loading', () => {
    vi.mocked(api.getAdminStats).mockReturnValue(new Promise(() => {}));
    render(<AdminOverviewPage />);

    expect(screen.getByText('Loading stats...')).toBeInTheDocument();
    expect(screen.getByTestId('page-controls')).toBeInTheDocument();
  });
});
