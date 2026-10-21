import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api } from '@/lib/api';
import { useEventExports } from '../useEventExports';

describe('useEventExports', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('warns when request export reports truncation and clears the warning on retry', async () => {
    const exportCsv = vi.spyOn(api, 'exportEventCsv')
      .mockResolvedValueOnce(true)
      .mockResolvedValueOnce(false);
    const { result } = renderHook(() => useEventExports('PARTY7', vi.fn()));

    await act(async () => result.current.handleExportCsv());
    expect(exportCsv).toHaveBeenCalledWith('PARTY7');
    expect(result.current.requestExportWarning).toBe('This CSV contains the first 10,000 requests only.');

    await act(async () => result.current.handleExportCsv());
    expect(result.current.requestExportWarning).toBeNull();
    expect(result.current.exporting).toBe(false);
  });

  it('warns when the play-history response has no truncation status', async () => {
    vi.spyOn(api, 'exportPlayHistoryCsv').mockResolvedValue(null);
    const { result } = renderHook(() => useEventExports('PARTY7', vi.fn()));

    await act(async () => result.current.handleExportPlayHistoryCsv());

    expect(result.current.playHistoryExportWarning).toBe(
      'The download did not include a truncation status. Verify it is complete before relying on it.',
    );
    expect(result.current.exportingHistory).toBe(false);
  });

  it('surfaces the API error and resets export state after a failed download', async () => {
    const setActionError = vi.fn();
    vi.spyOn(api, 'exportPlayHistoryCsv').mockRejectedValue(new ApiError('Export denied', 403));
    const { result } = renderHook(() => useEventExports('PARTY7', setActionError));

    await act(async () => result.current.handleExportPlayHistoryCsv());

    expect(setActionError).toHaveBeenCalledWith('Export denied');
    expect(result.current.exportingHistory).toBe(false);
  });
});
