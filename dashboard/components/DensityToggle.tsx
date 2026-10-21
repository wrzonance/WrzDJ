'use client';

interface DensityToggleProps {
  compact: boolean;
  onToggle: () => void;
}

/** Normal / dense request-list spacing switch for the event page. */
export function DensityToggle({ compact, onToggle }: DensityToggleProps) {
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={onToggle}
      aria-pressed={compact}
      title={compact ? 'Switch to normal density' : 'Switch to compact density'}
      aria-label={compact ? 'Compact mode on' : 'Compact mode off'}
    >
      <svg className="density-toggle-icon" viewBox="0 0 14 14" aria-hidden="true" focusable="false">
        {compact ? (
          <>
            <rect x="1" y="2" width="12" height="2" rx="1" />
            <rect x="1" y="6" width="12" height="2" rx="1" />
            <rect x="1" y="10" width="12" height="2" rx="1" />
          </>
        ) : (
          <>
            <rect x="1" y="2" width="12" height="3" rx="1.5" />
            <rect x="1" y="9" width="12" height="3" rx="1.5" />
          </>
        )}
      </svg>
      <span className="theme-toggle-label">{compact ? 'Dense' : 'Normal'}</span>
    </button>
  );
}
