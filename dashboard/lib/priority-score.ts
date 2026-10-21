/**
 * Priority score formatting and display utilities.
 *
 * Used by the DJ dashboard to render priority score badges
 * on request cards when sort=best_match is active (issue #478).
 */

export function formatPriorityScore(score: number | null | undefined): string {
  if (score === null || score === undefined) return '--';
  return `${Math.round(score * 100)}%`;
}

export function getPriorityScoreColor(score: number | null | undefined): string {
  if (score === null || score === undefined) return '#757575';
  if (score >= 0.7) return '#4ade80'; // green
  if (score >= 0.4) return '#fbbf24'; // amber
  return '#f87171'; // red
}
