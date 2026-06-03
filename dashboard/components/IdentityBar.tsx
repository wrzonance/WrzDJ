'use client';

import { useState } from 'react';
import EmailVerification from './EmailVerification';

interface Props {
  nickname: string;
  emailVerified: boolean;
  onVerified: () => void;
  picksLabel?: string;
  forceDark?: boolean;
  autoNamed?: boolean;
  onRename?: (newName: string) => Promise<void> | void;
}

export function IdentityBar({
  nickname,
  emailVerified,
  onVerified,
  picksLabel,
  forceDark,
  autoNamed,
  onRename,
}: Props) {
  const [showEmailForm, setShowEmailForm] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState('');
  const [savingName, setSavingName] = useState(false);

  const darkVars = forceDark ? ({
    '--card': '#1a1a1a',
    '--border-subtle': 'rgba(255,255,255,0.08)',
    '--text-secondary': '#9ca3af',
  } as React.CSSProperties) : undefined;

  return (
    <div className="identity-bar" style={darkVars}>
      <span className="identity-bar-name">👤 {nickname}</span>
      {autoNamed && onRename && !renaming && (
        <button className="identity-bar-action" onClick={() => { setDraft(''); setRenaming(true); }}>
          Add a name
        </button>
      )}
      {renaming && (
        <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
          <input
            className="input"
            aria-label="Your name"
            placeholder="Your name"
            value={draft}
            maxLength={30}
            onChange={(e) => setDraft(e.target.value)}
            autoFocus
          />
          <button
            className="btn btn-primary"
            disabled={!draft.trim() || savingName}
            onClick={async () => {
              setSavingName(true);
              try { await onRename!(draft.trim()); setRenaming(false); }
              finally { setSavingName(false); }
            }}
          >
            Save
          </button>
        </span>
      )}
      {emailVerified ? (
        <span className="identity-bar-verified">✓ Verified</span>
      ) : showEmailForm ? (
        <div className="identity-bar-email-form">
          <EmailVerification
            isVerified={false}
            onVerified={() => {
              onVerified();
              setShowEmailForm(false);
            }}
            onSkip={() => setShowEmailForm(false)}
          />
        </div>
      ) : (
        <button
          type="button"
          className="identity-bar-add-email"
          onClick={() => setShowEmailForm(true)}
        >
          <span className="identity-bar-pulse" aria-hidden="true" />
          + Add email →
        </button>
      )}
      {picksLabel && (
        <span style={{
          marginLeft: 'auto',
          fontFamily: 'var(--font-mono, monospace)',
          fontSize: '0.75rem',
          color: 'rgba(255,255,255,0.45)',
          letterSpacing: '0.04em',
          whiteSpace: 'nowrap',
        }}>
          {picksLabel}
        </span>
      )}
    </div>
  );
}
