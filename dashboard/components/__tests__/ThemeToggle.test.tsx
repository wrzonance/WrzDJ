import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { ThemeToggle } from '../ThemeToggle';
import * as HelpContext from '@/lib/help/HelpContext';
import type { HelpContextValue } from '@/lib/help/types';

vi.mock('@/lib/theme', () => ({
  useTheme: () => ({ theme: 'dark', toggleTheme: vi.fn() }),
}));

function makeHelpContext(overrides: Partial<HelpContextValue> = {}): HelpContextValue {
  return {
    helpMode: false,
    onboardingActive: false,
    currentStep: 0,
    activeSpotId: null,
    toggleHelpMode: vi.fn(),
    registerSpot: vi.fn(() => vi.fn()),
    getSpotsForPage: vi.fn(() => []),
    startOnboarding: vi.fn(),
    nextStep: vi.fn(),
    prevStep: vi.fn(),
    skipOnboarding: vi.fn(),
    hasSeenPage: vi.fn(() => false),
    ...overrides,
  };
}

beforeEach(() => {
  vi.spyOn(HelpContext, 'useHelp').mockReturnValue(makeHelpContext());
});

describe('ThemeToggle', () => {
  it('renders the toggle button when onboarding is not active', () => {
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(
      makeHelpContext({ onboardingActive: false })
    );
    render(<ThemeToggle />);
    expect(screen.getByRole('button', { name: /current theme/i })).toBeInTheDocument();
  });

  it('renders nothing when onboarding is active', () => {
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(
      makeHelpContext({ onboardingActive: true })
    );
    render(<ThemeToggle />);
    expect(screen.queryByRole('button', { name: /current theme/i })).not.toBeInTheDocument();
  });
});
