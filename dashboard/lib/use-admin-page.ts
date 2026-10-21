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
  const requestVersionRef = useRef(0);

  const reload = useCallback(async () => {
    const requestVersion = ++requestVersionRef.current;
    setLoading(true);
    try {
      const result = await loaderRef.current();
      if (requestVersion !== requestVersionRef.current) return;
      setData(result);
      setError('');
    } catch (err) {
      if (requestVersion !== requestVersionRef.current) return;
      const handler = onErrorRef.current;
      setError(handler ? handler(err) : 'Failed to load');
    } finally {
      if (requestVersion === requestVersionRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  useEffect(() => () => {
    requestVersionRef.current += 1;
  }, []);

  useAutoOnboarding(pageId, data !== null);

  return { data, loading, error, reload, setData };
}
