import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React, { createRef } from 'react';
import { OnboardingOverlay } from '../OnboardingOverlay';
import * as HelpContext from '@/lib/help/HelpContext';
import type { HelpContextValue } from '@/lib/help/types';
import type { HelpSpotConfig } from '@/lib/help/types';

function makeSpot(overrides: Partial<HelpSpotConfig> = {}): HelpSpotConfig {
  const el = document.createElement('div');
  el.getBoundingClientRect = () => ({
    top: 100, left: 50, width: 200, height: 40, bottom: 140, right: 250, x: 50, y: 100, toJSON: () => '',
  });
  const ref = createRef<HTMLElement>() as React.MutableRefObject<HTMLElement>;
  ref.current = el;
  return {
    id: 'spot-1',
    page: 'p',
    order: 1,
    title: 'Spot Title',
    description: 'Spot Description',
    ref,
    ...overrides,
  };
}

function makeContext(overrides: Partial<HelpContextValue> = {}): HelpContextValue {
  return {
    helpMode: true,
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

let mockCtx: HelpContextValue;

beforeEach(() => {
  mockCtx = makeContext();
  vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);
});

describe('OnboardingOverlay', () => {
  it('renders nothing when onboardingActive=false', () => {
    render(<OnboardingOverlay page="p" />);
    expect(screen.queryByTestId('onboarding-overlay')).not.toBeInTheDocument();
  });

  it('renders backdrop when active', () => {
    const spot = makeSpot();
    mockCtx = makeContext({
      onboardingActive: true,
      activeSpotId: 'spot-1',
      currentStep: 0,
      getSpotsForPage: vi.fn(() => [spot]),
    });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<OnboardingOverlay page="p" />);
    expect(screen.getByTestId('onboarding-overlay')).toBeInTheDocument();
  });

  it('shows current step title and description', () => {
    const spot = makeSpot({ title: 'Step One', description: 'First step' });
    mockCtx = makeContext({
      onboardingActive: true,
      activeSpotId: 'spot-1',
      currentStep: 0,
      getSpotsForPage: vi.fn(() => [spot]),
    });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<OnboardingOverlay page="p" />);
    expect(screen.getByText('Step One')).toBeInTheDocument();
    expect(screen.getByText('First step')).toBeInTheDocument();
  });

  it('shows Next, Skip buttons, hides Back on first step', () => {
    const spot = makeSpot();
    const spot2 = makeSpot({ id: 'spot-2', order: 2 });
    mockCtx = makeContext({
      onboardingActive: true,
      activeSpotId: 'spot-1',
      currentStep: 0,
      getSpotsForPage: vi.fn(() => [spot, spot2]),
    });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<OnboardingOverlay page="p" />);
    expect(screen.getByText('Next')).toBeInTheDocument();
    expect(screen.getByText('Skip tours')).toBeInTheDocument();
    expect(screen.queryByText('Back')).not.toBeInTheDocument();
  });

  it('shows Back when step > 0', () => {
    const spot1 = makeSpot({ id: 's1', order: 1 });
    const spot2 = makeSpot({ id: 's2', order: 2 });
    mockCtx = makeContext({
      onboardingActive: true,
      activeSpotId: 's2',
      currentStep: 1,
      getSpotsForPage: vi.fn(() => [spot1, spot2]),
    });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<OnboardingOverlay page="p" />);
    expect(screen.getByText('Back')).toBeInTheDocument();
  });

  it('shows step counter', () => {
    const spot1 = makeSpot({ id: 's1', order: 1 });
    const spot2 = makeSpot({ id: 's2', order: 2 });
    const spot3 = makeSpot({ id: 's3', order: 3 });
    mockCtx = makeContext({
      onboardingActive: true,
      activeSpotId: 's1',
      currentStep: 0,
      getSpotsForPage: vi.fn(() => [spot1, spot2, spot3]),
    });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<OnboardingOverlay page="p" />);
    expect(screen.getByText('Step 1 of 3')).toBeInTheDocument();
  });

  it('last step shows "Done" instead of "Next"', () => {
    const spot1 = makeSpot({ id: 's1', order: 1 });
    const spot2 = makeSpot({ id: 's2', order: 2 });
    mockCtx = makeContext({
      onboardingActive: true,
      activeSpotId: 's2',
      currentStep: 1,
      getSpotsForPage: vi.fn(() => [spot1, spot2]),
    });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<OnboardingOverlay page="p" />);
    expect(screen.getByText('Done')).toBeInTheDocument();
    expect(screen.queryByText('Next')).not.toBeInTheDocument();
  });

  it('Next calls nextStep', () => {
    const nextFn = vi.fn();
    const spot1 = makeSpot({ id: 's1', order: 1 });
    const spot2 = makeSpot({ id: 's2', order: 2 });
    mockCtx = makeContext({
      onboardingActive: true,
      activeSpotId: 's1',
      currentStep: 0,
      nextStep: nextFn,
      getSpotsForPage: vi.fn(() => [spot1, spot2]),
    });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<OnboardingOverlay page="p" />);
    fireEvent.click(screen.getByText('Next'));
    expect(nextFn).toHaveBeenCalledTimes(1);
  });

  it('Back calls prevStep', () => {
    const prevFn = vi.fn();
    const spot1 = makeSpot({ id: 's1', order: 1 });
    const spot2 = makeSpot({ id: 's2', order: 2 });
    mockCtx = makeContext({
      onboardingActive: true,
      activeSpotId: 's2',
      currentStep: 1,
      prevStep: prevFn,
      getSpotsForPage: vi.fn(() => [spot1, spot2]),
    });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<OnboardingOverlay page="p" />);
    fireEvent.click(screen.getByText('Back'));
    expect(prevFn).toHaveBeenCalledTimes(1);
  });

  it('Skip calls skipOnboarding', () => {
    const skipFn = vi.fn();
    const spot = makeSpot();
    mockCtx = makeContext({
      onboardingActive: true,
      activeSpotId: 'spot-1',
      currentStep: 0,
      skipOnboarding: skipFn,
      getSpotsForPage: vi.fn(() => [spot]),
    });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<OnboardingOverlay page="p" />);
    fireEvent.click(screen.getByText('Skip tours'));
    expect(skipFn).toHaveBeenCalledTimes(1);
  });

  it('Done calls nextStep (which auto-completes)', () => {
    const nextFn = vi.fn();
    const spot = makeSpot();
    mockCtx = makeContext({
      onboardingActive: true,
      activeSpotId: 'spot-1',
      currentStep: 0,
      nextStep: nextFn,
      getSpotsForPage: vi.fn(() => [spot]),
    });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<OnboardingOverlay page="p" />);
    fireEvent.click(screen.getByText('Done'));
    expect(nextFn).toHaveBeenCalledTimes(1);
  });

  it('Escape key calls skipOnboarding', () => {
    const skipFn = vi.fn();
    const spot = makeSpot();
    mockCtx = makeContext({
      onboardingActive: true,
      activeSpotId: 'spot-1',
      currentStep: 0,
      skipOnboarding: skipFn,
      getSpotsForPage: vi.fn(() => [spot]),
    });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<OnboardingOverlay page="p" />);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(skipFn).toHaveBeenCalledTimes(1);
  });

  it('positions card above spotlight when target is near viewport bottom', () => {
    const el = document.createElement('div');
    // Spot near the bottom of viewport (top: 700 in 768px window)
    el.getBoundingClientRect = () => ({
      top: 700, left: 50, width: 200, height: 40, bottom: 740, right: 250, x: 50, y: 700, toJSON: () => '',
    });
    const ref = createRef<HTMLElement>() as React.MutableRefObject<HTMLElement>;
    ref.current = el;
    const spot: HelpSpotConfig = { id: 'bottom-spot', page: 'p', order: 1, title: 'T', description: 'D', ref };

    mockCtx = makeContext({
      onboardingActive: true,
      activeSpotId: 'bottom-spot',
      currentStep: 0,
      getSpotsForPage: vi.fn(() => [spot]),
    });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    // jsdom window.innerHeight defaults to 768
    render(<OnboardingOverlay page="p" />);
    const card = document.querySelector('.onboarding-card') as HTMLElement;
    expect(card).toBeTruthy();
    // Card should be positioned using bottom instead of top (flipped above)
    expect(card.style.bottom).toBeTruthy();
    expect(card.style.top).toBeFalsy();
  });

  it('positions card below spotlight when target is near viewport top', () => {
    const spot = makeSpot(); // default: top: 100, bottom: 140
    mockCtx = makeContext({
      onboardingActive: true,
      activeSpotId: 'spot-1',
      currentStep: 0,
      getSpotsForPage: vi.fn(() => [spot]),
    });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<OnboardingOverlay page="p" />);
    const card = document.querySelector('.onboarding-card') as HTMLElement;
    expect(card).toBeTruthy();
    // Card should be below the spotlight (top style set)
    expect(card.style.top).toBeTruthy();
  });

  it('scrolls target element into view when it is off-screen', () => {
    const el = document.createElement('div');
    el.getBoundingClientRect = () => ({
      top: 1200, left: 50, width: 200, height: 40, bottom: 1240, right: 250, x: 50, y: 1200, toJSON: () => '',
    });
    el.scrollIntoView = vi.fn();
    const ref = createRef<HTMLElement>() as React.MutableRefObject<HTMLElement>;
    ref.current = el;
    const spot: HelpSpotConfig = { id: 'offscreen', page: 'p', order: 1, title: 'T', description: 'D', ref };

    mockCtx = makeContext({
      onboardingActive: true,
      activeSpotId: 'offscreen',
      currentStep: 0,
      getSpotsForPage: vi.fn(() => [spot]),
    });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<OnboardingOverlay page="p" />);
    expect(el.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'center' });
  });

  it('renders nothing when onboarding active but no spots found', () => {
    mockCtx = makeContext({
      onboardingActive: true,
      activeSpotId: 'missing',
      currentStep: 0,
      getSpotsForPage: vi.fn(() => []),
    });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<OnboardingOverlay page="p" />);
    expect(screen.queryByTestId('onboarding-overlay')).not.toBeInTheDocument();
  });
});
