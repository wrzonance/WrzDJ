'use client';

import { Dispatch, SetStateAction, useCallback, useEffect, useRef, useState } from 'react';
import { useHelp } from '@/lib/help/HelpContext';

export interface UseAdminPageConfig<T> {
  pageId: string;
  loader: () => Promise<T>;
  onError?: (error: unknown) => string;
}

export interface UseAdminPageResult<T> {
  data: T | null;
  loading: boolean;
  error: string;
  reload: () => Promise<void>;
  setData: Dispatch<SetStateAction<T | null>>;
}

export function useAdminPage<T>({
  pageId,
  loader,
  onError,
}: UseAdminPageConfig<T>): UseAdminPageResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const { hasSeenPage, startOnboarding, onboardingActive } = useHelp();

  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;
  // Last request wins: a slow earlier load must not overwrite a newer one's
  // data after the user changed page, filter, or search.
  const requestIdRef = useRef(0);

  const reload = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    try {
      const result = await loaderRef.current();
      if (requestId !== requestIdRef.current) return;
      setData(result);
      setError('');
    } catch (err) {
      if (requestId !== requestIdRef.current) return;
      const handler = onErrorRef.current;
      setError(handler ? handler(err) : 'Failed to load');
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  useEffect(() => {
    if (data !== null && !onboardingActive && !hasSeenPage(pageId)) {
      const timer = setTimeout(() => startOnboarding(pageId), 500);
      return () => clearTimeout(timer);
    }
  }, [data, onboardingActive, hasSeenPage, startOnboarding, pageId]);

  return { data, loading, error, reload, setData };
}
