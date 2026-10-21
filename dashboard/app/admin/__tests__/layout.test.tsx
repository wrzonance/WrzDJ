import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AdminLayout from '../layout';

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  logout: vi.fn(),
  pathname: '/admin',
  auth: { isAuthenticated: false, isLoading: true, role: null as string | null },
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mocks.push }),
  usePathname: () => mocks.pathname,
}));
vi.mock('next/link', () => ({
  default: ({ href, children, className }: {
    href: string;
    children: React.ReactNode;
    className?: string;
  }) => <a href={href} className={className}>{children}</a>,
}));
vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ ...mocks.auth, logout: mocks.logout }),
}));
vi.mock('@/components/ThemeToggle', () => ({ ThemeToggle: () => <button>Theme</button> }));

describe('admin layout access boundary', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.pathname = '/admin';
    mocks.auth = { isAuthenticated: false, isLoading: true, role: null };
  });

  it('keeps the protected content hidden while authentication is loading', () => {
    render(<AdminLayout><p>Protected admin data</p></AdminLayout>);

    expect(screen.getByText('Loading...')).toBeInTheDocument();
    expect(screen.queryByText('Protected admin data')).not.toBeInTheDocument();
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it.each([
    [false, 'admin', '/login'],
    [true, 'dj', '/dashboard'],
  ])('redirects unauthorized users away from admin pages', (isAuthenticated, role, destination) => {
    mocks.auth = { isAuthenticated, isLoading: false, role };

    render(<AdminLayout><p>Protected admin data</p></AdminLayout>);

    expect(screen.getByText('Loading...')).toBeInTheDocument();
    expect(screen.queryByText('Protected admin data')).not.toBeInTheDocument();
    expect(mocks.push).toHaveBeenCalledWith(destination);
  });

  it('renders admin navigation and delegates logout for an admin', () => {
    mocks.auth = { isAuthenticated: true, isLoading: false, role: 'admin' };
    mocks.pathname = '/admin/events';

    render(<AdminLayout><p>Protected admin data</p></AdminLayout>);

    expect(screen.getByText('Protected admin data')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Overview' })).toHaveAttribute('href', '/admin');
    expect(screen.getByRole('link', { name: 'Events' })).toHaveClass('active');
    fireEvent.click(screen.getByRole('button', { name: 'Logout' }));
    expect(mocks.logout).toHaveBeenCalledOnce();
  });
});
