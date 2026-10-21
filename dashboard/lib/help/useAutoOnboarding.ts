'use client';

import { useEffect } from 'react';
import { useHelp } from './HelpContext';

/** Delay before the tour opens, so the page settles after its data loads. */
const AUTO_START_DELAY_MS = 500;

/**
 * Auto-start the help tour for `page` once `ready` is true, unless the user has
 * already seen this page's tour or skipped tours altogether. One hook replaces the
 * per-page copies of this effect (#863).
 */
export function useAutoOnboarding(page: string, ready: boolean): void {
  const { hasSeenPage, startOnboarding, onboardingActive } = useHelp();

  useEffect(() => {
    if (!ready || onboardingActive || hasSeenPage(page)) return;
    const timer = setTimeout(() => startOnboarding(page), AUTO_START_DELAY_MS);
    return () => clearTimeout(timer);
  }, [page, ready, onboardingActive, hasSeenPage, startOnboarding]);
}
