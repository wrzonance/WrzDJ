import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useAutoOnboarding } from '../useAutoOnboarding';
import * as HelpContext from '../HelpContext';
import type { HelpContextValue } from '../types';

function makeContext(overrides: Partial<HelpContextValue> = {}): HelpContextValue {
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

describe('useAutoOnboarding', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('starts the tour for an unseen page once the page is ready', () => {
    const ctx = makeContext();
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(ctx);

    renderHook(() => useAutoOnboarding('dashboard', true));
    expect(ctx.startOnboarding).not.toHaveBeenCalled();

    vi.advanceTimersByTime(500);
    expect(ctx.startOnboarding).toHaveBeenCalledWith('dashboard');
  });

  it('does nothing while the page is not ready', () => {
    const ctx = makeContext();
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(ctx);

    renderHook(() => useAutoOnboarding('dashboard', false));
    vi.advanceTimersByTime(1000);
    expect(ctx.startOnboarding).not.toHaveBeenCalled();
  });

  it('does nothing for a page the user has already seen or skipped', () => {
    const ctx = makeContext({ hasSeenPage: vi.fn(() => true) });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(ctx);

    renderHook(() => useAutoOnboarding('dashboard', true));
    vi.advanceTimersByTime(1000);
    expect(ctx.startOnboarding).not.toHaveBeenCalled();
  });

  it('does not stack a second tour while one is active', () => {
    const ctx = makeContext({ onboardingActive: true });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(ctx);

    renderHook(() => useAutoOnboarding('dashboard', true));
    vi.advanceTimersByTime(1000);
    expect(ctx.startOnboarding).not.toHaveBeenCalled();
  });

  it('cancels the pending start when the page changes before the delay elapses', () => {
    const ctx = makeContext();
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(ctx);

    const { rerender } = renderHook(({ page }) => useAutoOnboarding(page, true), {
      initialProps: { page: 'event-manage' },
    });
    vi.advanceTimersByTime(200);
    rerender({ page: 'event-songs' });
    vi.advanceTimersByTime(500);

    expect(ctx.startOnboarding).toHaveBeenCalledTimes(1);
    expect(ctx.startOnboarding).toHaveBeenCalledWith('event-songs');
  });
});
