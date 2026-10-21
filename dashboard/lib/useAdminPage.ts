'use client';

import { Dispatch, SetStateAction, useCallback, useEffect, useRef, useState } from 'react';
import { useAutoOnboarding } from '@/lib/help/useAutoOnboarding';

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

  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const result = await loaderRef.current();
      setData(result);
      setError('');
    } catch (err) {
      const handler = onErrorRef.current;
      setError(handler ? handler(err) : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  useAutoOnboarding(pageId, data !== null);

  return { data, loading, error, reload, setData };
}
