import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api } from '@/lib/api';
import type { SongRequest } from '@/lib/api/types';
import { useEventQueueActions } from '../useEventQueueActions';

const request = (id: number, status: string) => ({ id, status }) as SongRequest;

describe('useEventQueueActions', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('replaces only the matching request after a status update', async () => {
    const updated = request(2, 'accepted');
    vi.spyOn(api, 'updateRequestStatus').mockResolvedValue(updated);
    const setAllRequests = vi.fn();
    const { result } = renderHook(() => useEventQueueActions({
      code: 'PARTY7', setAllRequests, refetchRequests: vi.fn(), setActionError: vi.fn(),
    }));

    await act(async () => result.current.updateStatus(2, 'accepted'));

    const updateState = setAllRequests.mock.calls[0][0];
    expect(updateState([request(1, 'new'), request(2, 'new'), request(3, 'new')])).toEqual([
      request(1, 'new'), updated, request(3, 'new'),
    ]);
    expect(result.current.updating).toBeNull();
  });

  it('removes the deleted request and refetches after accepting all', async () => {
    vi.spyOn(api, 'deleteRequest').mockResolvedValue(undefined);
    const acceptAll = vi.spyOn(api, 'acceptAllRequests').mockResolvedValue({
      status: 'ok', accepted_count: 2,
    });
    const setAllRequests = vi.fn();
    const refetchRequests = vi.fn();
    const { result } = renderHook(() => useEventQueueActions({
      code: 'PARTY7', setAllRequests, refetchRequests, setActionError: vi.fn(),
    }));

    await act(async () => result.current.handleDeleteRequest(2));
    const removeState = setAllRequests.mock.calls[0][0];
    expect(removeState([request(1, 'new'), request(2, 'new')])).toEqual([request(1, 'new')]);
    await act(async () => result.current.handleAcceptAll());

    expect(acceptAll).toHaveBeenCalledWith('PARTY7');
    expect(refetchRequests).toHaveBeenCalledOnce();
    expect(result.current.deletingRequest).toBeNull();
    expect(result.current.acceptingAll).toBe(false);
  });

  it('preserves API errors and resets the status update indicator after failure', async () => {
    const setActionError = vi.fn();
    vi.spyOn(api, 'updateRequestStatus').mockRejectedValue(new ApiError('Request is locked', 409));
    const { result } = renderHook(() => useEventQueueActions({
      code: 'PARTY7', setAllRequests: vi.fn(), refetchRequests: vi.fn(), setActionError,
    }));

    await act(async () => result.current.updateStatus(2, 'rejected'));

    expect(setActionError).toHaveBeenCalledWith('Request is locked');
    expect(result.current.updating).toBeNull();
  });
});
