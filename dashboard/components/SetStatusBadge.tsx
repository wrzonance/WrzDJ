import { getSetStatusMeta } from '@/lib/setbuilder-status';

/**
 * Canonical status display for a WrzDJSet set. Use this wherever a set's
 * lifecycle status appears (collaboration lists, version history, builder
 * header) so labelling and styling stay consistent. Styling lives in the
 * `.badge-set-*` rules in globals.css; semantics live in `lib/setbuilder-status`.
 */
export function SetStatusBadge({
  status,
  showTooltip = false,
}: {
  status: string;
  showTooltip?: boolean;
}) {
  const meta = getSetStatusMeta(status);
  return (
    <span
      className={meta.badgeClass}
      aria-label={`Status: ${meta.label}`}
      title={showTooltip ? meta.description : undefined}
    >
      {meta.label}
    </span>
  );
}
