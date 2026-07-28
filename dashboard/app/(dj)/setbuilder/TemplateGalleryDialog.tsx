'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { SetDetail, SetTemplate } from '@/lib/api-types';

interface TemplateGalleryDialogProps {
  onClose: () => void;
  /** Called with the freshly instantiated set so the caller can route to it. */
  onInstantiated: (set: SetDetail) => void;
}

/**
 * Per-DJ gallery of saved set templates, shown alongside the new-set flow. Instantiating a
 * template creates a fresh draft set pre-seeded with its curve/vibe/target structure and
 * empty (track_id=null) slots, ready for pool import + recompute. See
 * `server/app/services/setbuilder/set_templates.py:instantiate_template`.
 */
export default function TemplateGalleryDialog({ onClose, onInstantiated }: TemplateGalleryDialogProps) {
  const [templates, setTemplates] = useState<SetTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [instantiatingId, setInstantiatingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  useEffect(() => {
    api
      .listSetTemplates()
      .then((res) => setTemplates(res.templates))
      .catch(() => setError('Failed to load templates'))
      .finally(() => setLoading(false));
  }, []);

  // One mutation at a time for the whole dialog: per-card busy state alone
  // still leaves every OTHER card's buttons live, so a second click could
  // create a duplicate set or delete a template mid-instantiate.
  const mutating = instantiatingId !== null || deletingId !== null;

  const instantiate = async (templateId: number) => {
    if (mutating) return;
    setInstantiatingId(templateId);
    setError(null);
    try {
      const created = await api.instantiateSetTemplate(templateId);
      onInstantiated(created);
    } catch {
      setError('Failed to create set from template');
      setInstantiatingId(null);
    }
  };

  const remove = async (template: SetTemplate) => {
    if (mutating) return;
    if (!window.confirm(`Delete the "${template.name}" template? This cannot be undone.`)) return;
    setDeletingId(template.id);
    setError(null);
    try {
      await api.deleteSetTemplate(template.id);
      setTemplates((prev) => prev.filter((t) => t.id !== template.id));
    } catch {
      setError('Failed to delete template');
    } finally {
      setDeletingId(null);
    }
  };

  /** Ignore backdrop/Close while a mutation is in flight. */
  const closeIfIdle = () => {
    if (!mutating) onClose();
  };

  // Escape dismissal for keyboard-only users, same lock as closeIfIdle.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !mutating) onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [mutating, onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Start a set from a template"
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
        style={{
          maxWidth: 560,
          width: '90%',
          maxHeight: '80vh',
          display: 'flex',
          flexDirection: 'column',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ marginBottom: '0.5rem' }}>Start from a template</h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '1rem' }}>
          Creates a new draft set pre-seeded with a saved curve, vibe windows, and target
          settings — ready for pool import.
        </p>

        {error && (
          <p style={{ color: 'var(--color-danger)', fontSize: '0.875rem', marginBottom: '0.75rem' }}>
            {error}
          </p>
        )}

        {loading ? (
          <div className="loading">Loading templates...</div>
        ) : templates.length === 0 ? (
          <p style={{ color: 'var(--text-secondary)' }}>
            No templates saved yet. Save a set as a template to reuse its structure here.
          </p>
        ) : (
          <div style={{ overflowY: 'auto', display: 'grid', gap: '0.75rem' }}>
            {templates.map((template) => (
              <TemplateCard
                key={template.id}
                template={template}
                busyInstantiate={instantiatingId === template.id}
                busyDelete={deletingId === template.id}
                locked={mutating}
                onInstantiate={() => instantiate(template.id)}
                onDelete={() => remove(template)}
              />
            ))}
          </div>
        )}

        <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1rem' }}>
          <button
            type="button"
            className="btn"
            style={{ background: 'var(--surface-raised)' }}
            disabled={mutating}
            onClick={closeIfIdle}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

interface TemplateCardProps {
  template: SetTemplate;
  busyInstantiate: boolean;
  busyDelete: boolean;
  /** True while ANY card in the dialog is mutating — disables every action. */
  locked: boolean;
  onInstantiate: () => void;
  onDelete: () => void;
}

function TemplateCard({
  template,
  busyInstantiate,
  busyDelete,
  locked,
  onInstantiate,
  onDelete,
}: TemplateCardProps) {
  return (
    <div className="card" style={{ background: 'var(--surface-raised)', padding: '0.75rem 1rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
        <div>
          <h3 style={{ fontSize: '1rem', marginBottom: '0.25rem' }}>{template.name}</h3>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            <span className="badge">{template.slot_count} slots</span>
            <span className="badge">{template.curve_points.length} curve points</span>
            {template.vibe_theme && <span className="badge">{template.vibe_theme}</span>}
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start' }}>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            disabled={locked}
            onClick={onInstantiate}
          >
            {busyInstantiate ? 'Creating…' : 'Use template'}
          </button>
          <button type="button" className="btn btn-sm btn-danger" disabled={locked} onClick={onDelete}>
            {busyDelete ? 'Deleting…' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  );
}
