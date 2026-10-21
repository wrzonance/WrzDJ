import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { ThemeToggle } from '../ThemeToggle';
import { ThemeProvider } from '@/lib/theme';
import * as HelpContext from '@/lib/help/HelpContext';
import type { HelpContextValue } from '@/lib/help/types';

function makeHelpContext(overrides: Partial<HelpContextValue> = {}): HelpContextValue {
  return {
    helpMode: false,
    onboardingActive: false,
    currentStep: 0,
    activeSpotId: null,
    toggleHelpMode: () => {},
    registerSpot: () => () => {},
    getSpotsForPage: () => [],
    startOnboarding: () => {},
    nextStep: () => {},
    prevStep: () => {},
    skipOnboarding: () => {},
    hasSeenPage: () => false,
    ...overrides,
  };
}

function renderThemeToggle() {
  localStorage.setItem('wrzdj-theme', 'dark');
  return render(
    <ThemeProvider>
      <ThemeToggle />
    </ThemeProvider>,
  );
}

describe('ThemeToggle', () => {
  it('renders the toggle button when onboarding is not active', () => {
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(
      makeHelpContext({ onboardingActive: false })
    );
    renderThemeToggle();
    expect(screen.getByRole('button', { name: /current theme/i })).toBeInTheDocument();
  });

  it('renders nothing when onboarding is active', () => {
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(
      makeHelpContext({ onboardingActive: true })
    );
    renderThemeToggle();
    expect(screen.queryByRole('button', { name: /current theme/i })).not.toBeInTheDocument();
  });
});
