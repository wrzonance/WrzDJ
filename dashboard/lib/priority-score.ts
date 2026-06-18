/**
 * Priority score formatting and display utilities.
 *
 * Used by the DJ dashboard to render priority score badges
 * on request cards when sort=best_match is active (issue #478).
 */

/**
 * Format a priority score (0.0-1.0) as a percentage string.
 * Returns "--" for null/undefined scores.
 */
export function formatPriorityScore(score: number | null | undefined): string {
  if (score === null || score === undefined) return '--';
  return `${Math.round(score * 100)}%`;
}

/**
 * Get a CSS color for a priority score.
 * Green for high scores, amber for mid, red for low, gray for null.
 */
export function getPriorityScoreColor(score: number | null | undefined): string {
  if (score === null || score === undefined) return '#666';
  if (score >= 0.7) return '#4ade80'; // green
  if (score >= 0.4) return '#fbbf24'; // amber
  return '#f87171'; // red
}
