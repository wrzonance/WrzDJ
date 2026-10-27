'use client';

import { useEffect, useRef, useState } from 'react';
import { api, ApiError, type AdminGuest } from '@/lib/api';
import { useDialogFocus } from '@/lib/useDialogFocus';
import { guestDisplayName } from './guest-format';

interface GuestEditModalProps {
  guest: AdminGuest;
  onClose: () => void;
  onSaved: () => void;
}

type NicknameDraft = Record<number, string>;

function initialDraft(guest: AdminGuest): NicknameDraft {
  return Object.fromEntries(guest.events.map((m) => [m.event_id, m.nickname ?? '']));
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

export function GuestEditModal({ guest, onClose, onSaved }: GuestEditModalProps) {
  const [draft, setDraft] = useState<NicknameDraft>(() => initialDraft(guest));
  const [revokeEmail, setRevokeEmail] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<number, string>>({});
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  useDialogFocus(dialogRef);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const changedMemberships = guest.events.filter(
    (m) => draft[m.event_id].trim() !== (m.nickname ?? ''),
  );

  const saveNicknames = async (): Promise<boolean> => {
    const nextErrors: Record<number, string> = {};
    for (const membership of changedMemberships) {
      try {
        await api.updateAdminGuestProfile(guest.id, membership.event_id, {
          nickname: draft[membership.event_id].trim(),
        });
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          nextErrors[membership.event_id] = err.message;
        } else {
          throw err;
        }
      }
    }
    setFieldErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSaving(true);
    try {
      const nicknamesOk = await saveNicknames();
      if (revokeEmail) {
        await api.updateAdminGuest(guest.id, { revoke_email: true });
      }
      if (nicknamesOk) {
        onSaved();
      }
    } catch (err) {
      setError(errorMessage(err, 'Failed to update guest'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        ref={dialogRef}
        className="modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="guest-edit-title"
        tabIndex={-1}
      >
        <h2 id="guest-edit-title" style={{ marginBottom: '1rem' }}>Edit: {guestDisplayName(guest)}</h2>
        <form onSubmit={handleSubmit}>
          {guest.events.length === 0 && (
            <p className="guest-meta" style={{ marginBottom: '1rem' }}>
              This guest has not joined any events, so there is no nickname to edit.
            </p>
          )}
          {guest.events.map((membership) => {
            const inputId = `guest-nickname-${membership.event_id}`;
            const fieldError = fieldErrors[membership.event_id];
            return (
              <div className="form-group" key={membership.event_id}>
                <label htmlFor={inputId}>Nickname in {membership.name}</label>
                <input
                  id={inputId}
                  className="input"
                  value={draft[membership.event_id]}
                  maxLength={30}
                  placeholder="Leave blank to clear"
                  aria-invalid={fieldError ? true : undefined}
                  aria-describedby={fieldError ? `${inputId}-error` : undefined}
                  onChange={(e) =>
                    setDraft((prev) => ({ ...prev, [membership.event_id]: e.target.value }))
                  }
                />
                {fieldError && (
                  <div id={`${inputId}-error`} className="guest-field-error">
                    {fieldError}
                  </div>
                )}
              </div>
            );
          })}
          {guest.email_verified && (
            <div className="form-group">
              <label className="guest-checkbox">
                <input
                  type="checkbox"
                  checked={revokeEmail}
                  onChange={(e) => setRevokeEmail(e.target.checked)}
                />
                <span>Revoke verified email</span>
              </label>
              <div className="guest-meta">
                Forgets {guest.email_masked}. The guest can verify an address again later.
              </div>
            </div>
          )}
          {error && (
            <div className="guest-field-error" style={{ marginBottom: '1rem' }}>
              {error}
            </div>
          )}
          <div style={{ display: 'flex', gap: '1rem' }}>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
