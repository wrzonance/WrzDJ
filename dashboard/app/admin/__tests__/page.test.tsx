import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AdminOverviewPage from '../page';
import { api } from '@/lib/api';
import type { SystemStats } from '@/lib/api/types';

vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock('@/lib/help/HelpContext', () => ({
  useHelp: () => ({ hasSeenPage: () => true, startOnboarding: vi.fn(), onboardingActive: false }),
}));
vi.mock('@/components/PageControls', () => ({
  PageControls: ({ children }: { children?: React.ReactNode }) => <div data-testid="page-controls">{children}</div>,
}));
vi.mock('@/components/help/OnboardingOverlay', () => ({ OnboardingOverlay: () => null }));
vi.mock('@/components/help/HelpSpot', () => ({
  HelpSpot: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

const stats: SystemStats = {
  total_users: 12,
  active_users: 8,
  pending_users: 2,
  total_events: 20,
  active_events: 3,
  total_requests: 41,
};

describe('admin overview route', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('shows a loading state while the stats request is pending', () => {
    vi.spyOn(api, 'getAdminStats').mockReturnValue(new Promise(() => {}));

    render(<AdminOverviewPage />);

    expect(screen.getByText('Loading stats...')).toBeInTheDocument();
  });

  it('renders the returned counts and management links', async () => {
    vi.spyOn(api, 'getAdminStats').mockResolvedValue(stats);

    render(<AdminOverviewPage />);

    expect(await screen.findByText('Dashboard Overview')).toBeInTheDocument();
    expect(screen.getByText('Total Users').previousSibling).toHaveTextContent('12');
    expect(screen.getByText('Active Events').previousSibling).toHaveTextContent('3');
    expect(screen.getByText('Manage Users').closest('a')).toHaveAttribute('href', '/admin/users');
    expect(screen.getByText('Manage Events').closest('a')).toHaveAttribute('href', '/admin/events');
  });

  it('shows a safe error message if stats fail to load', async () => {
    vi.spyOn(api, 'getAdminStats').mockRejectedValue(new Error('secret backend detail'));

    render(<AdminOverviewPage />);

    expect(await screen.findByText('Failed to load stats')).toBeInTheDocument();
    expect(screen.queryByText('secret backend detail')).not.toBeInTheDocument();
  });
});
