'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { api } from '@/lib/api';
import type { SharedSetView } from '@/lib/api-types';

/** Format seconds as "1h 05m" / "45m". */
function formatDuration(totalSec: number): string {
  const hours = Math.floor(totalSec / 3600);
  const minutes = Math.round((totalSec % 3600) / 60);
  if (hours === 0) return `${minutes}m`;
  return `${hours}h ${String(minutes).padStart(2, '0')}m`;
}

function formatCurvePosition(sec: number): string {
  const minutes = Math.floor(sec / 60);
  const seconds = sec % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

/**
 * Public, view-only rendering of a shared set (issue #398).
 *
 * No auth, no mutation calls, no agent/export controls — the share token
 * only grants the single public read endpoint on the server, and this page
 * intentionally renders nothing interactive beyond scrolling.
 */
export default function SharedSetPage() {
  const params = useParams();
  const token = params.token as string;
  const [view, setView] = useState<SharedSetView | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!token) return;
    api
      .getSharedSet(token)
      .then(setView)
      .catch(() => setError(true));
  }, [token]);

  if (error) {
    return (
      <div className="container" style={{ maxWidth: 720, paddingTop: '4rem' }}>
        <div className="card" style={{ textAlign: 'center' }}>
          <h1 style={{ marginBottom: '0.5rem' }}>Set unavailable</h1>
          <p style={{ color: 'var(--text-secondary)' }}>
            This link is invalid or has been revoked.
          </p>
        </div>
      </div>
    );
  }

  if (!view) {
    return (
      <div className="container" style={{ maxWidth: 720 }}>
        <div className="loading">Loading…</div>
      </div>
    );
  }

  const chips: string[] = [];
  if (view.target_duration_sec != null) chips.push(formatDuration(view.target_duration_sec));
  if (view.bpm_floor != null && view.bpm_ceiling != null) {
    chips.push(`${view.bpm_floor}–${view.bpm_ceiling} BPM`);
  }
  if (view.vibe_theme) chips.push(view.vibe_theme);

  return (
    <div className="container" style={{ maxWidth: 720, paddingBottom: '3rem' }}>
      <header style={{ margin: '2rem 0 1.5rem' }}>
        <span
          className="badge"
          style={{ display: 'inline-block', marginBottom: '0.75rem' }}
          title="Shared read-only view"
        >
          View only
        </span>
        <h1 style={{ marginBottom: '0.5rem' }}>{view.name}</h1>
        {chips.length > 0 && (
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
            {chips.join(' · ')}
          </p>
        )}
      </header>

      <section className="card" style={{ marginBottom: '1.5rem' }} aria-label="Timeline">
        <h2 style={{ marginBottom: '1rem' }}>Timeline</h2>
        {view.slots.length === 0 ? (
          <p style={{ color: 'var(--text-secondary)' }}>No tracks yet.</p>
        ) : (
          <ol style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {view.slots.map((slot) => (
              <li
                key={slot.position}
                style={{
                  display: 'flex',
                  gap: '0.75rem',
                  alignItems: 'baseline',
                  padding: '0.5rem 0',
                  borderBottom: '1px solid var(--surface-raised)',
                }}
              >
                <span style={{ color: 'var(--text-secondary)', minWidth: '1.5rem' }}>
                  {slot.position}
                </span>
                <span style={{ flex: 1 }}>
                  {slot.track_id ?? <em style={{ color: 'var(--text-secondary)' }}>empty slot</em>}
                  {slot.locked && (
                    <span style={{ marginLeft: '0.5rem' }} title="Locked" aria-label="Locked">
                      🔒
                    </span>
                  )}
                  {slot.notes && (
                    <span
                      style={{
                        display: 'block',
                        color: 'var(--text-secondary)',
                        fontSize: '0.8125rem',
                      }}
                    >
                      {slot.notes}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="card" aria-label="Energy curve">
        <h2 style={{ marginBottom: '1rem' }}>Energy curve</h2>
        {view.curve_points.length === 0 ? (
          <p style={{ color: 'var(--text-secondary)' }}>No curve defined.</p>
        ) : (
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {view.curve_points.map((point) => (
              <li
                key={point.position_sec}
                style={{
                  display: 'flex',
                  gap: '0.75rem',
                  alignItems: 'baseline',
                  padding: '0.375rem 0',
                }}
              >
                <span style={{ color: 'var(--text-secondary)', minWidth: '3.5rem' }}>
                  {formatCurvePosition(point.position_sec)}
                </span>
                <span style={{ minWidth: '6rem' }}>Energy {point.energy}/10</span>
                {point.label && <span>{point.label}</span>}
                {(point.is_slow_window_start || point.is_slow_window_end) && (
                  <span style={{ color: 'var(--text-secondary)', fontSize: '0.8125rem' }}>
                    {point.is_slow_window_start ? 'slow window starts' : 'slow window ends'}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
