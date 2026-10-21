'use client';

import { useState } from 'react';
import { z } from 'zod';
import EmailVerification from '../../../../components/EmailVerification';

const nicknameSchema = z
  .string()
  .trim()
  .min(2, 'Nickname must be at least 2 characters')
  .max(30)
  .regex(/^[a-zA-Z0-9 _.-]+$/, 'Letters, numbers, spaces, . _ - only');

interface Props {
  emailVerified: boolean;
  initialNickname: string | null;
  onSave: (data: { nickname?: string }) => Promise<void>;
  onVerified: () => void;
}

export default function FeatureOptInPanel({ emailVerified, initialNickname, onSave, onVerified }: Props) {
  const [expanded, setExpanded] = useState(true);
  const [nickname, setNickname] = useState(initialNickname ?? '');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Hide once the guest either has a verified email OR has chosen a nickname and dismissed.
  if ((emailVerified || !expanded) && initialNickname !== null) return null;
  if (emailVerified && !expanded) return null;

  const submit = async () => {
    const payload: { nickname?: string } = {};

    const nickTrimmed = nickname.trim();
    if (nickTrimmed) {
      const nickResult = nicknameSchema.safeParse(nickTrimmed);
      if (!nickResult.success) {
        setError(nickResult.error.issues[0].message);
        return;
      }
      payload.nickname = nickResult.data;
    }

    if (Object.keys(payload).length === 0) {
      setError('Enter a nickname to save');
      return;
    }

    setError(null);
    setSaving(true);
    try {
      await onSave(payload);
    } catch (e) {
      setError(
        e instanceof Error && e.message.trim()
          ? e.message
          : 'Could not save your preferences. Please try again.',
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="collect-optin">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <h3 style={{ margin: 0 }}>Make it yours</h3>
        <button
          type="button"
          className="btn btn-sm collect-optin-dismiss"
          onClick={() => setExpanded(false)}
          aria-label="Close"
          style={{ padding: '0.25rem 0.5rem', lineHeight: 1 }}
        >
          ✕
        </button>
      </div>
      <p
        style={{
          fontSize: '0.875rem',
          color: 'var(--text-secondary)',
          marginBottom: '0.75rem',
        }}
      >
        Pick a nickname so the DJ knows who suggested what. Verify your email for extra perks.
      </p>
      <ul className="collect-optin-features">
        <li>Nickname appears next to your picks</li>
        <li>Email: notify me when my song plays</li>
        <li>Email: cross-device &quot;my picks&quot; and leaderboard position</li>
      </ul>

      <div className="form-group">
        <label htmlFor="collect-nickname">Nickname</label>
        <input
          id="collect-nickname"
          type="text"
          className="input"
          value={nickname}
          onChange={(e) => setNickname(e.target.value)}
          placeholder="DancingQueen"
          maxLength={30}
          required
        />
      </div>

      {error && <p role="alert" className="collection-fieldset-error">{error}</p>}

      <div className="collect-optin-actions">
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={submit}
          disabled={saving}
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>

      <EmailVerification isVerified={emailVerified} onVerified={onVerified} />
    </section>
  );
}
