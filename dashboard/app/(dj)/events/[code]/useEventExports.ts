'use client';

import { useState } from 'react';
import { api, ApiError } from '@/lib/api';

export function useEventExports(code: string, setActionError: (message: string | null) => void) {
  const [exporting, setExporting] = useState(false);
  const [exportingHistory, setExportingHistory] = useState(false);
  const [requestExportWarning, setRequestExportWarning] = useState<string | null>(null);
  const [playHistoryExportWarning, setPlayHistoryExportWarning] = useState<string | null>(null);

  const handleExportCsv = async () => {
    setExporting(true);
    setRequestExportWarning(null);
    try {
      const truncated = await api.exportEventCsv(code);
      setRequestExportWarning(truncated === true
        ? 'This CSV contains the first 10,000 requests only.'
        : truncated === null
          ? 'The download did not include a truncation status. Verify it is complete before relying on it.'
          : null);
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'Failed to export');
    } finally {
      setExporting(false);
    }
  };

  const handleExportPlayHistoryCsv = async () => {
    setExportingHistory(true);
    setPlayHistoryExportWarning(null);
    try {
      const truncated = await api.exportPlayHistoryCsv(code);
      setPlayHistoryExportWarning(truncated === true
        ? 'This CSV contains the first 10,000 play history entries only.'
        : truncated === null
          ? 'The download did not include a truncation status. Verify it is complete before relying on it.'
          : null);
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'Failed to export play history');
    } finally {
      setExportingHistory(false);
    }
  };

  return {
    exporting,
    exportingHistory,
    requestExportWarning,
    playHistoryExportWarning,
    handleExportCsv,
    handleExportPlayHistoryCsv,
  };
}
