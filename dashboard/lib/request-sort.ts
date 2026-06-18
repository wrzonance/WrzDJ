/**
 * DJ request-list sort metadata (issue #478).
 *
 * The backend exposes 8 sort fields with per-field default directions. The
 * dashboard mirrors those defaults so that changing the sort field snaps the
 * direction toggle to the field's natural default; a separate toggle flips it.
 *
 * Keep `SORT_FIELDS` / `SORT_FIELD_DEFAULT_DIRECTION` in sync with
 * server/app/schemas (RequestSort + per-field defaults).
 */

import type { RequestSort, SortDirection } from './api-types';

/** Sort options in dashboard display order. Best Match leads (former "priority"). */
export const SORT_FIELDS: readonly { value: RequestSort; label: string }[] = [
  { value: 'best_match', label: 'Best Match' },
  { value: 'date_requested', label: 'Date requested' },
  { value: 'date_accepted', label: 'Date accepted' },
  { value: 'upvotes', label: 'Upvotes' },
  { value: 'bpm', label: 'BPM' },
  { value: 'key', label: 'Key' },
  { value: 'title', label: 'Title' },
  { value: 'artist', label: 'Artist' },
] as const;

/** Per-field default direction (mirrors the backend's per-field defaults). */
export const SORT_FIELD_DEFAULT_DIRECTION: Record<RequestSort, SortDirection> = {
  date_requested: 'desc',
  date_accepted: 'desc',
  upvotes: 'desc',
  bpm: 'asc',
  key: 'asc',
  title: 'asc',
  artist: 'asc',
  best_match: 'desc',
};

/** Default sort field when no preference is stored. */
export const DEFAULT_SORT_FIELD: RequestSort = 'date_requested';

/** Type guard: is this string one of the known sort fields? */
export function isRequestSort(value: string): value is RequestSort {
  return SORT_FIELDS.some((f) => f.value === value);
}

/**
 * Migrate a legacy `wrzdj-sort-${code}` value (the #468 toggle) to a sort field.
 * `'priority'` → `best_match`; anything else falls back to `date_requested`.
 */
export function migrateLegacySort(legacy: string | null): RequestSort {
  return legacy === 'priority' ? 'best_match' : DEFAULT_SORT_FIELD;
}
