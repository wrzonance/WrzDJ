import { describe, expect, it, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useEventSortPreferences } from '../useEventSortPreferences';

describe('useEventSortPreferences', () => {
  beforeEach(() => localStorage.clear());

  // Regression for baseline 57cfcdc6867f: legacy sort values must be migrated once.
  it('persists the legacy sort migration and removes the old key', () => {
    localStorage.setItem('wrzdj-sort-EVT01', 'priority');

    const { result } = renderHook(() => useEventSortPreferences('EVT01'));

    expect(result.current.sortField).toBe('best_match');
    expect(result.current.sortDirection).toBe('desc');
    expect(localStorage.getItem('wrzdj-sortfield-EVT01')).toBe('best_match');
    expect(localStorage.getItem('wrzdj-sortdir-EVT01')).toBe('desc');
    expect(localStorage.getItem('wrzdj-sort-EVT01')).toBeNull();
  });
});
