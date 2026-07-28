'use client';

import { useState } from 'react';
import { api } from '@/lib/api';
import type { SetSummary, SetTemplate } from '@/lib/api-types';

interface SaveAsTemplateDialogProps {
  set: SetSummary;
  onClose: () => void;
  /** Called with the newly created template so callers can react (e.g. show a confirmation). */
  onSaved: (template: SetTemplate) => void;
}

const MAX_NAME_LENGTH = 120;

/**
 * Extracts a set's structure — curve, vibe windows, target settings — into a reusable
 * template. Track-specific data (pool assignments) is never copied; see
 * `server/app/services/setbuilder/set_templates.py:extract_template`.
 */
export default function SaveAsTemplateDialog({ set, onClose, onSaved }: SaveAsTemplateDialogProps) {
  const [name, setName] = useState(set.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmedName = name.trim();
  const canSave = trimmedName.length > 0 && trimmedName.length <= MAX_NAME_LENGTH && !busy;

  /** Ignore backdrop/Cancel while the save is in flight. */
  const closeIfIdle = () => {
    if (!busy) onClose();
  };

  const save = async () => {
    if (!canSave) return;
    setBusy(true);
    setError(null);
    try {
      const template = await api.saveSetAsTemplate(set.id, trimmedName);
      onSaved(template);
    } catch {
      setError('Failed to save template');
      setBusy(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-label={`Save ${set.name} as template`}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.6)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 100,
      }}
      onClick={closeIfIdle}
    >
      <div
        className="card"
        style={{ maxWidth: 480, width: '90%' }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ marginBottom: '0.5rem' }}>Save as template</h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '1rem' }}>
          Captures this set&rsquo;s curve, vibe windows, and target settings — not its tracks —
          so you can reuse the structure with a fresh pool.
        </p>

        {error && (
          <p style={{ color: 'var(--color-danger)', fontSize: '0.875rem', marginBottom: '0.75rem' }}>
            {error}
          </p>
        )}

        <div className="form-group">
          <label htmlFor="templateName">Template name</label>
          <input
            id="templateName"
            type="text"
            className="input"
            value={name}
            maxLength={MAX_NAME_LENGTH}
            autoFocus
            required
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1rem' }}>
          <button type="button" className="btn btn-primary" disabled={!canSave} onClick={save}>
            {busy ? 'Saving…' : 'Save template'}
          </button>
          <button
            type="button"
            className="btn"
            style={{ background: 'var(--surface-raised)' }}
            disabled={busy}
            onClick={closeIfIdle}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
