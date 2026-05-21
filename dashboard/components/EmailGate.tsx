'use client';

import { ReactNode } from 'react';
import EmailVerification from './EmailVerification';

interface Props {
  /** True when the calling page has determined the guest is email-verified. */
  verified: boolean;
  /** Called after the guest completes OTP — page should refetch profile/me. */
  onVerified: () => void;
  /** Wrapped UI; shown only when verified === true. */
  children: ReactNode;
}

/**
 * Full-screen blocker that requires email + Turnstile verification before
 * exposing collection-page features. Reuses EmailVerification (Turnstile +
 * OTP) and renders a modal overlay until the guest verifies.
 */
export default function EmailGate({ verified, onVerified, children }: Props) {
  if (verified) {
    return <>{children}</>;
  }

  return (
    <>
      <div className="email-gate-backdrop" aria-hidden={false}>
        <div className="email-gate-modal" role="dialog" aria-modal="true">
          <h2 className="email-gate-title">Verify your email to continue</h2>
          <p className="email-gate-subtitle">
            Pre-event submissions and votes require a verified email address. Your email is
            only used to prevent spam and is never shared.
          </p>
          <EmailVerification isVerified={false} onVerified={onVerified} />
        </div>
      </div>
      {/* Render children behind the gate so they're ready when verification completes */}
      <div className="email-gate-hidden" aria-hidden="true">
        {children}
      </div>
    </>
  );
}
