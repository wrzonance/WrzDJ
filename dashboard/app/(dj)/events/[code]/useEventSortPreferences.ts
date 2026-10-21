'use client';

import { useCallback, useState } from 'react';
import type { RequestSort, SortDirection } from '@/lib/api/types';
import { SORT_FIELD_DEFAULT_DIRECTION, isRequestSort, migrateLegacySort } from '@/lib/requests/request-sort';

function readStoredSortField(code: string): RequestSort {
  try {
    const storedField = localStorage.getItem('wrzdj-sortfield-' + code);
    if (storedField && isRequestSort(storedField)) return storedField;
    const legacyKey = 'wrzdj-sort-' + code;
    const legacyValue = localStorage.getItem(legacyKey);
    const migratedField = migrateLegacySort(legacyValue);
    if (legacyValue !== null) {
      localStorage.setItem('wrzdj-sortfield-' + code, migratedField);
      localStorage.setItem(
        'wrzdj-sortdir-' + code,
        SORT_FIELD_DEFAULT_DIRECTION[migratedField],
      );
      localStorage.removeItem(legacyKey);
    }
    return migratedField;
  } catch {
    return migrateLegacySort(null);
  }
}

export function useEventSortPreferences(code: string) {
  const [sortField, setSortField] = useState<RequestSort>(() => readStoredSortField(code));
  const [sortDirection, setSortDirection] = useState<SortDirection>(() => {
    try {
      const storedDir = localStorage.getItem('wrzdj-sortdir-' + code);
      if (storedDir === 'asc' || storedDir === 'desc') return storedDir;
    } catch {
      // localStorage unavailable
    }
    return SORT_FIELD_DEFAULT_DIRECTION[readStoredSortField(code)];
  });

  const handleSortFieldChange = useCallback((field: RequestSort) => {
    const direction = SORT_FIELD_DEFAULT_DIRECTION[field];
    setSortField(field);
    setSortDirection(direction);
    try {
      localStorage.setItem('wrzdj-sortfield-' + code, field);
      localStorage.setItem('wrzdj-sortdir-' + code, direction);
    } catch {
      // localStorage unavailable
    }
  }, [code]);

  const handleSortDirectionToggle = useCallback(() => {
    setSortDirection((prev) => {
      const next: SortDirection = prev === 'asc' ? 'desc' : 'asc';
      try {
        localStorage.setItem('wrzdj-sortdir-' + code, next);
      } catch {
        // localStorage unavailable
      }
      return next;
    });
  }, [code]);

  return { sortField, sortDirection, handleSortFieldChange, handleSortDirectionToggle };
}
