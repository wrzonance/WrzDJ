import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, type DisplaySettingsResponse, type Event } from '@/lib/api';
import { useEventDisplaySettings } from '../useEventDisplaySettings';

const settingsResponse: DisplaySettingsResponse = {
  status: 'ok',
  kiosk_display_only: false,
  now_playing_auto_hide_minutes: 30,
  now_playing_hidden: false,
  requests_open: true,
};

describe('useEventDisplaySettings', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('does not submit an auto-hide timeout outside the 1–1440 minute range', async () => {
    const update = vi.spyOn(api, 'setAutoHideMinutes');
    const { result } = renderHook(() => useEventDisplaySettings({
      code: 'PARTY7',
      event: null,
      setEvent: vi.fn(),
      setActionError: vi.fn(),
    }));

    act(() => result.current.setAutoHideInput('1441'));
    await act(async () => result.current.handleSaveAutoHide());

    expect(update).not.toHaveBeenCalled();
    expect(result.current.savingAutoHide).toBe(false);
  });

  it('saves the maximum supported auto-hide value and reflects the server response', async () => {
    const update = vi.spyOn(api, 'setAutoHideMinutes').mockResolvedValue(settingsResponse);
    const { result } = renderHook(() => useEventDisplaySettings({
      code: 'PARTY7',
      event: null,
      setEvent: vi.fn(),
      setActionError: vi.fn(),
    }));

    act(() => result.current.setAutoHideInput('1440'));
    await act(async () => result.current.handleSaveAutoHide());

    expect(update).toHaveBeenCalledWith('PARTY7', 1440);
    expect(result.current.autoHideMinutes).toBe(30);
    expect(result.current.autoHideInput).toBe('30');
    expect(result.current.savingAutoHide).toBe(false);
  });

  it('surfaces an API error when the now-playing visibility update fails', async () => {
    const setActionError = vi.fn();
    vi.spyOn(api, 'setNowPlayingVisibility').mockRejectedValue(
      new ApiError('Display is unavailable', 503),
    );
    const { result } = renderHook(() => useEventDisplaySettings({
      code: 'PARTY7',
      event: null,
      setEvent: vi.fn(),
      setActionError,
    }));

    await act(async () => result.current.handleToggleNowPlaying());

    expect(api.setNowPlayingVisibility).toHaveBeenCalledWith('PARTY7', true);
    expect(setActionError).toHaveBeenCalledWith('Display is unavailable');
    expect(result.current.togglingNowPlaying).toBe(false);
    expect(result.current.nowPlayingHidden).toBe(false);
  });

  it('surfaces a request availability error without changing the last known setting', async () => {
    const setActionError = vi.fn();
    vi.spyOn(api, 'setRequestsOpen').mockRejectedValue(new ApiError('Request toggle failed', 503));
    const { result } = renderHook(() => useEventDisplaySettings({
      code: 'PARTY7', event: null, setEvent: vi.fn(), setActionError,
    }));

    await act(async () => result.current.handleToggleRequests());

    expect(api.setRequestsOpen).toHaveBeenCalledWith('PARTY7', false);
    expect(setActionError).toHaveBeenCalledWith('Request toggle failed');
    expect(result.current.requestsOpen).toBe(true);
    expect(result.current.togglingRequests).toBe(false);
  });

  it('surfaces a display-only error without changing the last known setting', async () => {
    const setActionError = vi.fn();
    vi.spyOn(api, 'setKioskDisplayOnly').mockRejectedValue(new ApiError('Display update failed', 503));
    const { result } = renderHook(() => useEventDisplaySettings({
      code: 'PARTY7', event: null, setEvent: vi.fn(), setActionError,
    }));

    await act(async () => result.current.handleToggleDisplayOnly());

    expect(api.setKioskDisplayOnly).toHaveBeenCalledWith('PARTY7', true);
    expect(setActionError).toHaveBeenCalledWith('Display update failed');
    expect(result.current.kioskDisplayOnly).toBe(false);
    expect(result.current.togglingDisplayOnly).toBe(false);
  });

  it('surfaces a frictionless join error without changing the last known event', async () => {
    const setActionError = vi.fn();
    const setEvent = vi.fn();
    const event = { code: 'PARTY7' } as Event;
    vi.spyOn(api, 'updateEvent').mockRejectedValue(new ApiError('Frictionless update failed', 503));
    const { result } = renderHook(() => useEventDisplaySettings({
      code: 'PARTY7', event, setEvent, setActionError,
    }));

    await act(async () => result.current.handleToggleFrictionless());

    expect(api.updateEvent).toHaveBeenCalledWith('PARTY7', { frictionless_join: true });
    expect(setActionError).toHaveBeenCalledWith('Frictionless update failed');
    expect(setEvent).not.toHaveBeenCalled();
    expect(result.current.frictionlessJoin).toBe(false);
    expect(result.current.togglingFrictionless).toBe(false);
  });
});
