import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api } from '@/lib/api';
import { useKioskDisplayData } from './useKioskDisplayData';

vi.mock('@/lib/api', () => ({
  api: {
    getKioskDisplay: vi.fn(),
    getNowPlaying: vi.fn(),
    getPlayHistory: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
  PUBLIC_PAGE_MAX: 500,
}));
vi.mock('@/lib/use-event-stream', () => ({ useEventStream: vi.fn() }));
vi.mock('@/lib/usePollingLoop', () => ({ usePollingLoop: vi.fn() }));

describe('useKioskDisplayData request lifecycle', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getNowPlaying).mockResolvedValue(null);
    vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });
  });

  it('does not publish a terminal error or stop result after unmount', async () => {
    let rejectRequest!: (error: Error) => void;
    vi.mocked(api.getKioskDisplay).mockImplementation(() => new Promise((_, reject) => {
      rejectRequest = reject;
    }));

    const { result, unmount } = renderHook(() => useKioskDisplayData('EVENT-A'));
    let pending!: Promise<boolean>;
    act(() => { pending = result.current.loadDisplay(); });
    unmount();

    await act(async () => rejectRequest(new ApiError('Event was removed', 404)));

    await expect(pending).resolves.toBe(true);
  });
});
