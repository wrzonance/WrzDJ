import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useDjAccess } from '../use-dj-access';

const mocks = vi.hoisted(() => ({
  auth: { isAuthenticated: false, isLoading: true, role: null as string | null },
  push: vi.fn(),
}));

vi.mock('@/lib/auth', () => ({ useAuth: () => mocks.auth }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: mocks.push }) }));

describe('useDjAccess', () => {
  beforeEach(() => {
    mocks.auth.isAuthenticated = false;
    mocks.auth.isLoading = true;
    mocks.auth.role = null;
    mocks.push.mockReset();
  });

  it('does not redirect or grant access while authentication is loading', () => {
    const { result } = renderHook(() => useDjAccess());

    expect(result.current.canAccess).toBe(false);
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it('sends unauthenticated visitors to login after auth resolves', async () => {
    mocks.auth.isLoading = false;
    const { result } = renderHook(() => useDjAccess());

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith('/login'));
    expect(result.current.canAccess).toBe(false);
  });

  it('sends authenticated pending users to the pending page without granting access', async () => {
    mocks.auth.isAuthenticated = true;
    mocks.auth.isLoading = false;
    mocks.auth.role = 'pending';
    const { result } = renderHook(() => useDjAccess());

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith('/pending'));
    expect(result.current.canAccess).toBe(false);
  });

  it.each(['dj', 'admin'])('grants access to the %s role without redirecting', (role) => {
    mocks.auth.isAuthenticated = true;
    mocks.auth.isLoading = false;
    mocks.auth.role = role;
    const { result } = renderHook(() => useDjAccess());

    expect(result.current.canAccess).toBe(true);
    expect(mocks.push).not.toHaveBeenCalled();
  });
});
