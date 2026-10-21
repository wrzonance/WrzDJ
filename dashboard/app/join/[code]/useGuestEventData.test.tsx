import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { api, stream } = vi.hoisted(() => ({
  api: {
    getPublicEvent: vi.fn(),
    checkHasRequested: vi.fn(),
    getCollectProfile: vi.fn(),
    getPublicRequests: vi.fn(),
  },
  stream: { handlers: null as null | Record<string, (value: never) => void> },
}));

vi.mock('@/lib/api', () => ({ api }));
vi.mock('@/lib/use-event-stream', () => ({
  useEventStream: vi.fn((_code: string | null, handlers: Record<string, (value: never) => void>) => {
    stream.handlers = handlers;
    return { connected: false };
  }),
}));

import { useGuestEventData } from './useGuestEventData';

const eventFor = (code: string, name: string) => ({
  name,
  collection_code: code,
  requests_open: true,
  phase: 'live' as const,
  submission_cap_per_guest: 5,
  banner_url: null,
  banner_colors: null,
});

function setDefaultResponses() {
  api.getPublicEvent.mockImplementation(async (code: string) => eventFor(code, `Event ${code}`));
  api.checkHasRequested.mockResolvedValue({ has_requested: true });
  api.getCollectProfile.mockResolvedValue({ email_verified: false });
  api.getPublicRequests.mockResolvedValue({ requests: [], now_playing: null });
}

describe('useGuestEventData', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stream.handlers = null;
    setDefaultResponses();
  });

  it('discards responses from the previous route code', async () => {
    // Regression for baseline 57cfcdc6867f: a late fetch must not replace the newly selected event.
    let resolveFirstEvent!: (event: ReturnType<typeof eventFor>) => void;
    api.getPublicEvent
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirstEvent = resolve; }))
      .mockResolvedValueOnce(eventFor('TEST02', 'Second Event'));

    const options = (code: string) => ({
      code,
      enabled: true,
      myRequestIds: new Set<number>(),
      onMyRequestStatusChanged: vi.fn(),
    });
    const { result, rerender } = renderHook(({ code }) => useGuestEventData(options(code)), {
      initialProps: { code: 'TEST01' },
    });
    await waitFor(() => expect(api.getPublicEvent).toHaveBeenCalledWith('TEST01'));

    rerender({ code: 'TEST02' });
    await waitFor(() => expect(result.current.event?.name).toBe('Second Event'));

    await act(async () => {
      resolveFirstEvent(eventFor('TEST01', 'First Event'));
    });

    expect(result.current.event?.name).toBe('Second Event');
    expect(result.current.guestRequests).toEqual([]);
  });

  it('refreshes data for stream events and forwards only this guest’s status updates', async () => {
    const onMyRequestStatusChanged = vi.fn();
    const { result } = renderHook(() => useGuestEventData({
      code: 'TEST01',
      enabled: true,
      myRequestIds: new Set([44]),
      onMyRequestStatusChanged,
    }));
    await waitFor(() => expect(result.current.event?.name).toBe('Event TEST01'));
    await waitFor(() => expect(api.getPublicRequests).toHaveBeenCalled());

    act(() => {
      stream.handlers?.onRequestStatusChanged?.({
        request_id: 44,
        status: 'accepted',
        title: 'My Song',
      } as never);
      stream.handlers?.onRequestStatusChanged?.({
        request_id: 45,
        status: 'accepted',
        title: 'Other Song',
      } as never);
    });

    expect(onMyRequestStatusChanged).toHaveBeenCalledTimes(1);
    expect(onMyRequestStatusChanged).toHaveBeenCalledWith({
      request_id: 44,
      status: 'accepted',
      title: 'My Song',
    });
    expect(api.getPublicRequests).toHaveBeenCalledTimes(3);
  });
});
