import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, type Event } from '@/lib/api';
import { useEventLifecycleActions } from '../useEventLifecycleActions';

const event = { expires_at: '2030-04-05T06:07:00Z' } as Event;

function setup(initialEvent: Event | null = event) {
  const setEvent = vi.fn();
  const router = { push: vi.fn() };
  const setActionError = vi.fn();
  const hook = renderHook(() => useEventLifecycleActions({
    code: 'PARTY7', event: initialEvent, setEvent, router, setActionError,
  }));
  return { ...hook, setEvent, router, setActionError };
}

describe('useEventLifecycleActions', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('does not open expiry editing without a loaded event', () => {
    const { result } = setup(null);

    act(() => result.current.handleEditExpiry());

    expect(result.current.editingExpiry).toBe(false);
    expect(result.current.newExpiryDate).toBe('');
  });

  it('saves the edited local expiry as an ISO timestamp and updates the event', async () => {
    const updated = { expires_at: '2031-08-09T10:11:00.000Z' } as Event;
    const update = vi.spyOn(api, 'updateEvent').mockResolvedValue(updated);
    const { result, setEvent } = setup();

    act(() => {
      result.current.handleEditExpiry();
      result.current.setNewExpiryDate('2031-08-09T10:11');
    });
    await act(async () => result.current.handleSaveExpiry());

    expect(update).toHaveBeenCalledWith('PARTY7', { expires_at: new Date('2031-08-09T10:11').toISOString() });
    expect(setEvent).toHaveBeenCalledWith(updated);
    expect(result.current.editingExpiry).toBe(false);
    expect(result.current.updatingExpiry).toBe(false);
  });

  it('redirects after deletion, and surfaces API failure while closing the confirmation', async () => {
    const remove = vi.spyOn(api, 'deleteEvent').mockResolvedValue(undefined);
    const success = setup();
    await act(async () => success.result.current.handleDeleteEvent());

    expect(remove).toHaveBeenCalledWith('PARTY7');
    expect(success.router.push).toHaveBeenCalledWith('/dashboard');

    const setActionError = vi.fn();
    const router = { push: vi.fn() };
    vi.spyOn(api, 'deleteEvent').mockRejectedValue(new ApiError('Event has active requests', 409));
    const { result } = renderHook(() => useEventLifecycleActions({
      code: 'PARTY7', event, setEvent: vi.fn(), router, setActionError,
    }));
    act(() => result.current.setShowDeleteConfirm(true));

    await act(async () => result.current.handleDeleteEvent());

    expect(setActionError).toHaveBeenCalledWith('Event has active requests');
    expect(result.current.deleting).toBe(false);
    expect(result.current.showDeleteConfirm).toBe(false);
    expect(router.push).not.toHaveBeenCalled();
  });
});
