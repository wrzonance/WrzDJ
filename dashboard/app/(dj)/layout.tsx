'use client';

import { type ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { ThemeToggle } from '@/components/ThemeToggle';

export default function DJLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  // Setbuilder pages place real actions in the top-right corner, so the
  // floating toggle would overlap them — those pages render it inline instead.
  const floatingToggle = !pathname?.startsWith('/setbuilder');

  return (
    <>
      {floatingToggle && (
        <div style={{
          position: 'fixed',
          top: '1rem',
          right: '4.5rem',
          zIndex: 1050,
        }}>
          <ThemeToggle />
        </div>
      )}
      {children}
    </>
  );
}
