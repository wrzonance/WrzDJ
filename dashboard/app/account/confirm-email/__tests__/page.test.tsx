import { act, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => {
  let releaseSearchParams!: () => void;
  const searchParamsReady = new Promise<void>((resolve) => {
    releaseSearchParams = resolve;
  });

  return {
    searchParamsLoaded: false,
    searchParamsReady,
    releaseSearchParams,
    push: vi.fn(),
    confirmEmailChange: vi.fn(),
  };
});

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mocks.push }),
  useSearchParams: () => {
    if (!mocks.searchParamsLoaded) throw mocks.searchParamsReady;
    return { get: (key: string) => (key === 'token' ? 'validtoken123' : null) };
  },
}));

vi.mock('@/lib/api', () => ({
  api: { confirmEmailChange: (...args: unknown[]) => mocks.confirmEmailChange(...args) },
}));

import ConfirmEmailPage from '../page';

describe('ConfirmEmailPage', () => {
  beforeEach(() => {
    mocks.searchParamsLoaded = false;
    mocks.confirmEmailChange.mockReset().mockResolvedValue(undefined);
    mocks.push.mockReset();
  });

  it('keeps the client content behind its loading boundary until search params are ready', async () => {
    render(<ConfirmEmailPage />);

    expect(screen.getByText('Loading…')).toBeInTheDocument();

    await act(async () => {
      mocks.searchParamsLoaded = true;
      mocks.releaseSearchParams();
    });

    expect(await screen.findByText('Email address updated!')).toBeInTheDocument();
    expect(mocks.confirmEmailChange).toHaveBeenCalledWith('validtoken123');
  });
});
