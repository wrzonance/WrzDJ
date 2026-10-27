'use client';

import { createContext, useCallback, useContext, useRef, useState, ReactNode } from 'react';
import { api } from '@/lib/api';
import type { HelpSpotConfig, HelpContextValue } from './types';
import {
  isPageSeen,
  markPageSeen,
  readFallbackSeen,
  writeFallbackSeen,
  TOURS_SKIPPED,
} from './seen-pages';
import { isHelpDisabled } from './is-help-disabled';

const HelpContext = createContext<HelpContextValue | null>(null);

/** Seen on this account (server-initialised set) or in this browser (fallback). */
function isSeen(id: string): boolean {
  return isPageSeen(id) || readFallbackSeen(id);
}

function persistSeen(id: string): void {
  markPageSeen(id);
  writeFallbackSeen(id);
  api.markHelpPageSeen(id).catch(() => {});
}

export function HelpProvider({ children }: { children: ReactNode }) {
  const [helpMode, setHelpMode] = useState(false);
  const [onboardingActive, setOnboardingActive] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [activeSpotId, setActiveSpotId] = useState<string | null>(null);
  const spotsRef = useRef<Map<string, HelpSpotConfig>>(new Map());
  const onboardingPageRef = useRef<string | null>(null);
  // Help mode as it was before the tour switched it on, restored when the tour ends.
  const helpModeBeforeTourRef = useRef(false);

  const [isDisabled] = useState(isHelpDisabled);

  const toggleHelpMode = useCallback(() => {
    if (isDisabled) return;
    setHelpMode((prev) => !prev);
  }, [isDisabled]);

  const registerSpot = useCallback((config: HelpSpotConfig): (() => void) => {
    spotsRef.current.set(config.id, config);
    return () => {
      spotsRef.current.delete(config.id);
    };
  }, []);

  const getSpotsForPage = useCallback((page: string): HelpSpotConfig[] => {
    return Array.from(spotsRef.current.values())
      .filter((s) => s.page === page)
      .sort((a, b) => a.order - b.order);
  }, []);

  const startOnboarding = useCallback((page: string) => {
    if (isDisabled) return;
    const spots = getSpotsForPage(page);
    if (spots.length === 0) return;
    onboardingPageRef.current = page;
    setHelpMode((prev) => {
      helpModeBeforeTourRef.current = prev;
      return true;
    });
    setOnboardingActive(true);
    setCurrentStep(0);
    setActiveSpotId(spots[0].id);
  }, [isDisabled, getSpotsForPage]);

  /** End the tour, recording `seenId` (the page, or the account-wide skip marker). */
  const endOnboarding = useCallback((seenId: string | null) => {
    setOnboardingActive(false);
    setCurrentStep(0);
    setActiveSpotId(null);
    setHelpMode(helpModeBeforeTourRef.current);
    if (seenId) persistSeen(seenId);
    onboardingPageRef.current = null;
  }, []);

  const nextStep = useCallback(() => {
    const page = onboardingPageRef.current;
    if (!page) return;
    const spots = getSpotsForPage(page);
    const next = currentStep + 1;
    if (next >= spots.length) {
      endOnboarding(page);
    } else {
      setCurrentStep(next);
      setActiveSpotId(spots[next].id);
    }
  }, [currentStep, getSpotsForPage, endOnboarding]);

  const prevStep = useCallback(() => {
    const page = onboardingPageRef.current;
    if (!page || currentStep <= 0) return;
    const spots = getSpotsForPage(page);
    const prev = currentStep - 1;
    setCurrentStep(prev);
    setActiveSpotId(spots[prev].id);
  }, [currentStep, getSpotsForPage]);

  // Skipping is an account-wide opt-out (#863): no page auto-starts its tour again.
  const skipOnboarding = useCallback(() => {
    endOnboarding(TOURS_SKIPPED);
  }, [endOnboarding]);

  /** End the tour (Escape): marks only the current page seen, not the account-wide skip. */
  const dismissOnboarding = useCallback(() => {
    endOnboarding(onboardingPageRef.current);
  }, [endOnboarding]);

  const hasSeenPage = useCallback((page: string): boolean => {
    if (isDisabled) return true;
    return isSeen(TOURS_SKIPPED) || isSeen(page);
  }, [isDisabled]);

  return (
    <HelpContext.Provider
      value={{
        helpMode,
        onboardingActive,
        currentStep,
        activeSpotId,
        toggleHelpMode,
        registerSpot,
        getSpotsForPage,
        startOnboarding,
        nextStep,
        prevStep,
        skipOnboarding,
        dismissOnboarding,
        hasSeenPage,
      }}
    >
      {children}
    </HelpContext.Provider>
  );
}

export function useHelp(): HelpContextValue {
  const context = useContext(HelpContext);
  if (!context) {
    throw new Error('useHelp must be used within a HelpProvider');
  }
  return context;
}
