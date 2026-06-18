/**
 * Pre-event pending-review sort metadata (issue #478).
 *
 * The pending-review list is a focused subset of the DJ request-sort surface:
 * every row is `status="new"`, so bpm/key/date_accepted/best_match aren't
 * meaningful or displayed. We offer only the five options below.
 *
 * "Review order" is the backend default (vote-ranked: votes desc, age asc) and
 * is requested by sending NO `sort` param — so it has no direction toggle. The
 * remaining options map 1:1 onto `RequestSort` field values with per-field
 * default directions mirrored from the backend.
 */

import type { RequestSort, SortDirection } from './api-types';

/** Sentinel for the default vote-ranked order (sends no `sort` param). */
export const REVIEW_ORDER = 'review_order' as const;

/** A pending-review sort selection: either the sentinel or a real field. */
export type PendingReviewSort = typeof REVIEW_ORDER | RequestSort;

/** Sort options in display order. Review order leads (the backend default). */
export const PENDING_REVIEW_SORT_FIELDS: readonly {
  value: PendingReviewSort;
  label: string;
}[] = [
  { value: REVIEW_ORDER, label: 'Review order' },
  { value: 'upvotes', label: 'Upvotes' },
  { value: 'date_requested', label: 'Date requested' },
  { value: 'title', label: 'Title' },
  { value: 'artist', label: 'Artist' },
] as const;

/** Per-field default direction (mirrors the backend's per-field defaults). */
export const PENDING_REVIEW_DEFAULT_DIRECTION: Record<RequestSort, SortDirection> = {
  upvotes: 'desc',
  date_requested: 'desc',
  title: 'asc',
  artist: 'asc',
  // Unused by the pending-review UI, but kept exhaustive for the union.
  date_accepted: 'desc',
  bpm: 'asc',
  key: 'asc',
  best_match: 'desc',
};

/**
 * Resolve a pending-review selection into the `getPendingReview` query params.
 * "Review order" sends nothing (the backend default); a real field sends both
 * `sort` and `direction`.
 */
export function toPendingReviewParams(
  sort: PendingReviewSort,
  direction: SortDirection,
): { sort?: RequestSort; direction?: SortDirection } {
  if (sort === REVIEW_ORDER) return {};
  return { sort, direction };
}
