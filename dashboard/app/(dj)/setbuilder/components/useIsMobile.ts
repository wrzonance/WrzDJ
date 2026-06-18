'use client';

import { useEffect, useState } from 'react';

/**
 * Tracks whether the viewport is at or below a mobile breakpoint.
 *
 * Hydration-safe: starts as `false` (desktop) so the server render and the
 * first client render agree, then updates after mount and on every change.
 */
export function useIsMobile(maxWidthPx = 720): boolean {
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const query = window.matchMedia(`(max-width: ${maxWidthPx}px)`);
    const update = () => setIsMobile(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, [maxWidthPx]);

  return isMobile;
}
