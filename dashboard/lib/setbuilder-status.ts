import type { SetSummary } from './api-types';

/**
 * Canonical metadata for WrzDJSet set-lifecycle statuses.
 *
 * Single source of truth for how a set's status is labelled and styled across
 * the app. It lands ahead of its first on-screen use on purpose: upcoming
 * surfaces (multi-DJ collaboration, set versioning) will surface status, and
 * centralising it here keeps those additions to a one-liner.
 *
 * To add a status: extend the `status` union in api-types.ts, then add an entry
 * below — `SetStatusBadge` and every consumer pick it up automatically.
 */

export type SetStatus = SetSummary['status'];

export interface SetStatusMeta {
  /** Human-facing label. */
  label: string;
  /** Global badge classes; composes with the base `.badge`. */
  badgeClass: string;
  /** Short explanation, suitable for a tooltip. */
  description: string;
}

export const SET_STATUS_META: Record<SetStatus, SetStatusMeta> = {
  draft: {
    label: 'Draft',
    badgeClass: 'badge badge-set-draft',
    description: 'Work in progress — freely editable.',
  },
  locked: {
    label: 'Locked',
    badgeClass: 'badge badge-set-locked',
    description: 'Finalized — editing is restricted.',
  },
  exported: {
    label: 'Exported',
    badgeClass: 'badge badge-set-exported',
    description: 'Pushed to an external service.',
  },
};

const FALLBACK_META: SetStatusMeta = {
  label: 'Unknown',
  badgeClass: 'badge badge-set-draft',
  description: 'Unrecognized status.',
};

/** Resolve display metadata for a status, tolerant of unknown values. */
export function getSetStatusMeta(status: string): SetStatusMeta {
  return (SET_STATUS_META as Record<string, SetStatusMeta>)[status] ?? FALLBACK_META;
}
