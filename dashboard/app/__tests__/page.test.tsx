import { act, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Home from '../page';

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  auth: { isAuthenticated: false, isLoading: true },
}));

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock('@/lib/auth', () => ({ useAuth: () => mocks.auth }));

describe('home route', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.auth.isAuthenticated = false;
    mocks.auth.isLoading = true;
  });

  it('shows a loading state without redirecting while auth is unresolved', () => {
    render(<Home />);

    expect(screen.getByText('Loading...')).toBeInTheDocument();
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it.each([
    [true, '/dashboard'],
    [false, '/login'],
  ])('redirects after auth resolves (authenticated=%s)', async (isAuthenticated, destination) => {
    mocks.auth.isAuthenticated = isAuthenticated;
    mocks.auth.isLoading = false;

    render(<Home />);
    await act(async () => {});

    expect(mocks.push).toHaveBeenCalledWith(destination);
  });
});
