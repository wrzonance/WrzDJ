'use client';

import { useEffect, useState } from 'react';
import { useHelp } from '@/lib/help/HelpContext';

interface OnboardingOverlayProps {
  page: string;
}

export function OnboardingOverlay({ page }: OnboardingOverlayProps) {
  const { onboardingActive, currentStep, getSpotsForPage, nextStep, prevStep, skipOnboarding } = useHelp();
  const [spotRect, setSpotRect] = useState<DOMRect | null>(null);

  const spots = getSpotsForPage(page);
  const totalSteps = spots.length;
  const currentSpot = spots[currentStep] ?? null;
  const isLastStep = currentStep >= totalSteps - 1;

  useEffect(() => {
    if (!onboardingActive || !currentSpot?.ref?.current) return;

    const el = currentSpot.ref.current;
    const rect = el.getBoundingClientRect();
    const vh = window.innerHeight;

    // Scroll element into view if it's off-screen or mostly hidden
    if (rect.top > vh || rect.bottom < 0 || rect.top > vh * 0.85) {
      el.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
    }

    const updateRect = () => {
      if (currentSpot.ref.current) {
        setSpotRect(currentSpot.ref.current.getBoundingClientRect());
      }
    };

    // Small delay after potential scroll to get accurate position
    const timer = setTimeout(updateRect, 100);
    updateRect();

    window.addEventListener('resize', updateRect);
    window.addEventListener('scroll', updateRect, true);
    return () => {
      clearTimeout(timer);
      window.removeEventListener('resize', updateRect);
      window.removeEventListener('scroll', updateRect, true);
    };
  }, [onboardingActive, currentSpot]);

  useEffect(() => {
    if (!onboardingActive) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        skipOnboarding();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onboardingActive, skipOnboarding]);

  if (!onboardingActive || totalSteps === 0 || !currentSpot) return null;

  const padding = 8;
  const cardHeight = 180; // approximate height of the onboarding card
  const gap = padding + 12;

  // Determine if card should flip above the spotlight
  const flipAbove = spotRect
    ? spotRect.bottom + gap + cardHeight > window.innerHeight
    : false;

  return (
    <div data-testid="onboarding-overlay">
      {/* Backdrop with spotlight cutout */}
      {spotRect && (
        <div
          className="onboarding-backdrop"
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 1050,
            pointerEvents: 'none',
          }}
        >
          <div
            className="onboarding-spotlight"
            style={{
              position: 'absolute',
              top: spotRect.top - padding,
              left: spotRect.left - padding,
              width: spotRect.width + padding * 2,
              height: spotRect.height + padding * 2,
              borderRadius: '8px',
              boxShadow: '0 0 0 9999px rgba(0, 0, 0, 0.7)',
            }}
          />
        </div>
      )}

      {/* Step card */}
      <div
        className="onboarding-card"
        style={{
          position: 'fixed',
          zIndex: 1060,
          ...(spotRect
            ? flipAbove
              ? { bottom: window.innerHeight - spotRect.top + gap }
              : { top: spotRect.bottom + gap }
            : { top: '50%', transform: 'translate(-50%, -50%)' }),
          left: spotRect ? Math.max(16, Math.min(spotRect.left, window.innerWidth - 340)) : '50%',
        }}
      >
        <div className="onboarding-step-counter">
          Step {currentStep + 1} of {totalSteps}
        </div>
        <h3 className="onboarding-card-title">{currentSpot.title}</h3>
        <p className="onboarding-card-desc">{currentSpot.description}</p>
        <div className="onboarding-nav">
          <button className="btn btn-sm" style={{ background: '#333' }} onClick={skipOnboarding}>
            Skip
          </button>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            {currentStep > 0 && (
              <button className="btn btn-sm" style={{ background: '#333' }} onClick={prevStep}>
                Back
              </button>
            )}
            <button className="btn btn-primary btn-sm" onClick={nextStep}>
              {isLastStep ? 'Done' : 'Next'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
