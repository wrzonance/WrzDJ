import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, type Event } from '@/lib/api';
import { useEventBannerActions } from '../useEventBannerActions';

function fileInput(file: File | null) {
  const input = document.createElement('input');
  input.type = 'file';
  Object.defineProperty(input, 'files', { configurable: true, value: file ? [file] : [] });
  Object.defineProperty(input, 'value', {
    configurable: true,
    writable: true,
    value: file ? 'cover.png' : '',
  });
  return input;
}

function changeEvent(target: HTMLInputElement) {
  return { target } as unknown as React.ChangeEvent<HTMLInputElement>;
}

describe('useEventBannerActions', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('rejects banners larger than 5 MiB and clears the file input', async () => {
    const setActionError = vi.fn();
    const upload = vi.spyOn(api, 'uploadEventBanner');
    const { result } = renderHook(() => useEventBannerActions({
      code: 'PARTY7',
      setEvent: vi.fn(),
      setActionError,
    }));
    const input = fileInput(new File([new Uint8Array(5 * 1024 * 1024 + 1)], 'cover.png'));

    await act(async () => {
      await result.current.handleBannerSelect(changeEvent(input));
    });

    expect(setActionError).toHaveBeenCalledWith('File size must be under 5MB');
    expect(input.value).toBe('');
    expect(upload).not.toHaveBeenCalled();
    expect(result.current.uploadingBanner).toBe(false);
  });

  it('uploads a valid banner, publishes the returned event, and clears the input', async () => {
    const updatedEvent = {} as Event;
    const setEvent = vi.fn();
    const upload = vi.spyOn(api, 'uploadEventBanner').mockResolvedValue(updatedEvent);
    const { result } = renderHook(() => useEventBannerActions({
      code: 'PARTY7',
      setEvent,
      setActionError: vi.fn(),
    }));
    const file = new File([new Uint8Array(5 * 1024 * 1024)], 'cover.png', { type: 'image/png' });
    const input = fileInput(file);

    await act(async () => {
      await result.current.handleBannerSelect(changeEvent(input));
    });

    expect(upload).toHaveBeenCalledWith('PARTY7', file);
    expect(setEvent).toHaveBeenCalledWith(updatedEvent);
    expect(input.value).toBe('');
    expect(result.current.uploadingBanner).toBe(false);
  });

  it('preserves API error messages when deleting a banner fails', async () => {
    const setActionError = vi.fn();
    vi.spyOn(api, 'deleteEventBanner').mockRejectedValue(new ApiError('Banner is in use', 409));
    const { result } = renderHook(() => useEventBannerActions({
      code: 'PARTY7',
      setEvent: vi.fn(),
      setActionError,
    }));

    await act(async () => {
      await result.current.handleDeleteBanner();
    });

    expect(api.deleteEventBanner).toHaveBeenCalledWith('PARTY7');
    expect(setActionError).toHaveBeenCalledWith('Banner is in use');
  });
});
