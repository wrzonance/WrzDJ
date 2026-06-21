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

import type { StatusFilter } from '@/app/(dj)/events/[code]/components/types';

import type { RequestSort, SortDirection } from './api-types';
import { camelotOrdinal } from './camelot';

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

/**
 * Client-side sort/filter/count helpers (issue #489).
 *
 * The dashboard loads the whole bounded request set once, then sorts/filters/
 * counts in memory. These comparators MUST mirror
 * server/app/services/request_sort.py exactly so rows never jump between the
 * optimistic-patch view and the post-refetch view: every sort ends with a
 * deterministic `id DESC` tie-break; nullable `accepted_at`/`bpm` sort nulls-last
 * in both directions; `title`/`artist` compare case-insensitively; `key` sorts by
 * the Camelot ordinal with the same `(isNull, ordinal, title, artist, -id)` tuple
 * as `key_sorted`.
 */

/** Minimal structural row both SongRequest (main) and PendingReviewRow share. */
export interface SortableRequestRow {
  id: number;
  created_at: string;
  accepted_at?: string | null;
  vote_count: number;
  bpm?: number | null;
  musical_key?: string | null;
  song_title: string;
  artist: string;
  status: string;
}

/** The 7 fields sortable entirely client-side (everything except best_match). */
export type ClientSortField = Exclude<RequestSort, 'best_match'>;

const toTimestamp = (iso: string | null | undefined): number | null =>
  iso ? Date.parse(iso) : null;

/** Nulls-last numeric compare for a given direction (mirrors SQL nullslast). */
function compareNullableNumber(a: number | null, b: number | null, desc: boolean): number {
  const aNull = a === null;
  const bNull = b === null;
  if (aNull && bNull) return 0;
  if (aNull) return 1; // nulls last, both directions
  if (bNull) return -1;
  return desc ? b - a : a - b;
}

/** Case-insensitive string compare matching SQL `lower()` ordering (not locale). */
function compareString(a: string, b: string, desc: boolean): number {
  const x = a.toLowerCase();
  const y = b.toLowerCase();
  if (x === y) return 0;
  const cmp = x < y ? -1 : 1;
  return desc ? -cmp : cmp;
}

/** Pure comparator mirroring request_sort.py for a single client-sortable field. */
function comparator(field: ClientSortField, direction: SortDirection) {
  const desc = direction === 'desc';
  return (a: SortableRequestRow, b: SortableRequestRow): number => {
    let primary = 0;
    switch (field) {
      case 'date_requested':
        primary = compareNullableNumber(toTimestamp(a.created_at), toTimestamp(b.created_at), desc);
        break;
      case 'date_accepted':
        primary = compareNullableNumber(
          toTimestamp(a.accepted_at ?? null),
          toTimestamp(b.accepted_at ?? null),
          desc,
        );
        break;
      case 'upvotes':
        primary = desc ? b.vote_count - a.vote_count : a.vote_count - b.vote_count;
        break;
      case 'bpm':
        primary = compareNullableNumber(a.bpm ?? null, b.bpm ?? null, desc);
        break;
      case 'title':
        primary = compareString(a.song_title, b.song_title, desc);
        break;
      case 'artist':
        primary = compareString(a.artist, b.artist, desc);
        break;
      case 'key': {
        primary = compareNullableNumber(
          camelotOrdinal(a.musical_key),
          camelotOrdinal(b.musical_key),
          desc,
        );
        // key_sorted ties break by title then artist ASCENDING regardless of
        // direction, then by id DESC.
        if (primary === 0) primary = compareString(a.song_title, b.song_title, false);
        if (primary === 0) primary = compareString(a.artist, b.artist, false);
        break;
      }
    }
    return primary !== 0 ? primary : b.id - a.id; // id DESC tie-break
  };
}

/** Sort rows client-side for a simple field. Returns a new array (no mutation). */
export function sortRequests<T extends SortableRequestRow>(
  rows: readonly T[],
  field: ClientSortField,
  direction: SortDirection,
): T[] {
  return [...rows].sort(comparator(field, direction));
}

const EMPTY_STATUS_COUNTS: Record<StatusFilter, number> = {
  all: 0,
  new: 0,
  accepted: 0,
  playing: 0,
  played: 0,
  rejected: 0,
};

/** Per-status counts (+ all) from the in-memory set — correct by construction. */
export function computeStatusCounts(
  rows: readonly SortableRequestRow[],
): Record<StatusFilter, number> {
  const counts: Record<StatusFilter, number> = { ...EMPTY_STATUS_COUNTS };
  for (const r of rows) {
    counts.all += 1;
    // Own-property check (not `in`) so prototype keys like "toString" never match.
    if (r.status !== 'all' && Object.prototype.hasOwnProperty.call(counts, r.status)) {
      counts[r.status as StatusFilter] += 1;
    }
  }
  return counts;
}

/**
 * Coerce a server `status_counts` map into the strict StatusFilter-keyed record
 * (issue #521). Used on the capped path, where the in-memory set is truncated and
 * `computeStatusCounts` would undercount: the backend's authoritative counts are
 * pagination-independent. Missing keys default to 0; unknown keys are ignored.
 */
export function normalizeStatusCounts(
  raw: Record<string, number> | null | undefined,
): Record<StatusFilter, number> {
  const counts: Record<StatusFilter, number> = { ...EMPTY_STATUS_COUNTS };
  if (!raw) return counts;
  for (const key of Object.keys(counts) as StatusFilter[]) {
    const value = raw[key];
    if (typeof value === 'number' && Number.isFinite(value)) counts[key] = value;
  }
  return counts;
}

/** Filter rows by status tab; 'all' returns the full set. */
export function filterByStatus<T extends SortableRequestRow>(
  rows: readonly T[],
  filter: StatusFilter,
): T[] {
  if (filter === 'all') return [...rows];
  return rows.filter((r) => r.status === filter);
}
