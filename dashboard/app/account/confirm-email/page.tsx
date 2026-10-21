import { Suspense } from 'react';
import { ConfirmEmailContent } from './ConfirmEmailContent';

export default function ConfirmEmailPage() {
  return (
    <Suspense
      fallback={
        <main style={{ padding: '4rem', textAlign: 'center' }}>
          <p style={{ color: 'var(--text-secondary)' }}>Loading…</p>
        </main>
      }
    >
      <ConfirmEmailContent />
    </Suspense>
  );
}
