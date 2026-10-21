'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

interface GuestExperienceSectionProps {
  initialFrictionlessDefault: boolean;
}

export default function GuestExperienceSection({
  initialFrictionlessDefault,
}: GuestExperienceSectionProps) {
  const [enabled, setEnabled] = useState(initialFrictionlessDefault);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setEnabled(initialFrictionlessDefault);
  }, [initialFrictionlessDefault]);

  const handleToggle = async () => {
    const next = !enabled;
    setSaving(true);
    setError('');
    try {
      await api.updateMyPreferences({ frictionless_join_default: next });
      setEnabled(next);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not save preference');
    } finally {
      setSaving(false);
    }
  };

  return (
    <section style={{ background: 'var(--card)', borderRadius: '0.75rem', padding: '1.5rem', marginTop: '1.5rem' }}>
      <h2 style={{ marginTop: 0, marginBottom: '1.25rem', fontSize: '1.1rem' }}>Guest Experience</h2>
      <label style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <input
          type="checkbox"
          checked={enabled}
          disabled={saving}
          onChange={handleToggle}
          aria-label="Frictionless join by default"
        />
        <span>
          Frictionless join by default (new events)
          <br />
          <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
            New events let guests skip the nickname/email step and get an auto-generated name.
          </span>
        </span>
      </label>
      {error && (
        <p role="alert" style={{ color: 'var(--color-danger)', fontSize: '0.875rem', marginTop: '0.75rem' }}>
          {error}
        </p>
      )}
    </section>
  );
}
