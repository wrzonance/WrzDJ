import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, type CollectionSettingsResponse } from '@/lib/api';

interface UseCollectionSettingsOptions {
  code: string;
  enabled: boolean;
}

export function useCollectionSettings({ code, enabled }: UseCollectionSettingsOptions) {
  const latestRequest = useRef(0);
  const currentCode = useRef(code);
  currentCode.current = code;

  const [loaded, setLoaded] = useState<{ code: string; settings: CollectionSettingsResponse } | null>(null);
  const [request, setRequest] = useState<{
    code: string;
    loading: boolean;
    error: string | null;
  }>({ code, loading: false, error: null });

  const settings = loaded?.code === code ? loaded.settings : null;
  const loading = request.code === code && request.loading;
  const error = request.code === code ? request.error : null;

  const load = useCallback(async () => {
    const requestedCode = code;
    const requestId = ++latestRequest.current;
    setRequest({ code: requestedCode, loading: true, error: null });

    try {
      const next = await api.getCollectionSettings(requestedCode);
      if (currentCode.current === requestedCode && latestRequest.current === requestId) {
        setLoaded({ code: requestedCode, settings: next });
      }
    } catch (err) {
      if (currentCode.current === requestedCode && latestRequest.current === requestId) {
        setRequest({
          code: requestedCode,
          loading: true,
          error: err instanceof ApiError ? err.message : 'Failed to load pre-event settings',
        });
      }
    } finally {
      if (currentCode.current === requestedCode && latestRequest.current === requestId) {
        setRequest((current) => ({ ...current, loading: false }));
      }
    }
  }, [code]);

  useEffect(() => {
    if (enabled && !settings) void load();
  }, [enabled, settings, load]);

  useEffect(() => () => {
    latestRequest.current += 1;
  }, []);

  const updateSettings = useCallback((next: Partial<CollectionSettingsResponse>) => {
    setLoaded((current) => current?.code === code
      ? { ...current, settings: { ...current.settings, ...next } }
      : current);
  }, [code]);

  const replaceSettings = useCallback((settings: CollectionSettingsResponse) => {
    setLoaded({ code, settings });
  }, [code]);

  return { settings, loading, error, load, updateSettings, replaceSettings };
}
