/** Day-of-month ordinal suffix: 1→st, 2→nd, 3→rd, 11–13→th, 21→st, … */
export function ordinalSuffix(day: number): string {
  const rem100 = day % 100;
  if (rem100 >= 11 && rem100 <= 13) return 'th';
  switch (day % 10) {
    case 1:
      return 'st';
    case 2:
      return 'nd';
    case 3:
      return 'rd';
    default:
      return 'th';
  }
}

/**
 * Format a request timestamp for the DJ queue, in the viewer's local time zone.
 *
 * Same calendar day as `now`: 24h time only (e.g. `14:30:05`) — compact for
 * normal single-day/live events. Any earlier day (long-running collects span
 * days): `Month DDth, HH:MM:SS` (e.g. `June 17th, 09:12:44`) so the date is
 * surfaced exactly when the time alone is ambiguous.
 */
export function formatRequestTimestamp(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  const time = d.toLocaleTimeString(undefined, {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
  if (d.toDateString() === now.toDateString()) {
    return time;
  }
  const month = d.toLocaleString(undefined, { month: 'long' });
  return `${month} ${d.getDate()}${ordinalSuffix(d.getDate())}, ${time}`;
}
