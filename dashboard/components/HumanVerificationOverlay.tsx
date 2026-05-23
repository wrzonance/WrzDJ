'use client';

import { ReactNode } from 'react';
import type { HumanVerificationState } from '../lib/useHumanVerification';

interface Props {
  state: HumanVerificationState;
  widgetContainerRef: React.RefObject<HTMLDivElement | null>;
  onRetry: () => void;
  children: ReactNode;
}

/**
 * Blocks all page UI until the visitor's wrzdj_human cookie is established.
 * Provides a stable widget container the useHumanVerification hook can render
 * Turnstile into across every non-verified state, so Cloudflare's escalation
 * from invisible to visible challenge always has a reachable DOM node.
 */
export default function HumanVerificationOverlay({
  state,
  widgetContainerRef,
  onRetry,
  children,
}: Props) {
  if (state === 'verified') {
    return <>{children}</>;
  }

  return (
    <div className="hv-overlay-backdrop">
      <div className="hv-overlay-modal" role="dialog" aria-live="polite">
        {(state === 'idle' || state === 'loading') && <LoadingPanel />}
        {state === 'challenge' && <ChallengePanel />}
        {state === 'failed' && <FailedPanel onRetry={onRetry} />}

        <div
          ref={widgetContainerRef}
          data-testid="hv-widget-container"
          style={{
            marginTop: state === 'challenge' ? '1rem' : 0,
            minHeight: state === 'challenge' ? '65px' : 0,
            opacity: state === 'challenge' ? 1 : 0,
            pointerEvents: state === 'challenge' ? 'auto' : 'none',
            transition: 'opacity 120ms ease, min-height 120ms ease',
          }}
        />
      </div>
    </div>
  );
}

function LoadingPanel() {
  return (
    <>
      <div className="hv-overlay-spinner" aria-label="Verifying" />
      <h2 className="hv-overlay-title">Just a moment</h2>
      <p className="hv-overlay-body">
        We&apos;re verifying your browser before you start picking songs. This usually takes a
        second.
      </p>
      <p className="hv-overlay-footnote">Powered by Cloudflare Turnstile</p>
    </>
  );
}

function ChallengePanel() {
  return (
    <>
      <h2 className="hv-overlay-title">One more step</h2>
      <p className="hv-overlay-body">Please complete the security check below.</p>
    </>
  );
}

function FailedPanel({ onRetry }: { onRetry: () => void }) {
  return (
    <>
      <h2 className="hv-overlay-title">Verification didn&apos;t go through</h2>
      <p className="hv-overlay-body">
        Some privacy tools (Brave Shields, strict tracking protection, VPNs) can interfere. Try
        again, or open this page in a different browser.
      </p>
      <button type="button" className="hv-overlay-retry" onClick={onRetry}>
        Try again
      </button>
    </>
  );
}
