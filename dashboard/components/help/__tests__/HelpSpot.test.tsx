import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { HelpSpot } from '../HelpSpot';
import * as HelpContext from '@/lib/help/HelpContext';
import type { HelpContextValue } from '@/lib/help/types';

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
    dismissOnboarding: vi.fn(),
    hasSeenPage: vi.fn(() => false),
    ...overrides,
  };
}

let mockCtx: HelpContextValue;

beforeEach(() => {
  mockCtx = makeContext();
  vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);
});

describe('HelpSpot', () => {
  it('renders children', () => {
    render(
      <HelpSpot spotId="s1" page="p" order={1} title="T" description="D">
        <button>Click me</button>
      </HelpSpot>
    );
    expect(screen.getByRole('button', { name: 'Click me' })).toBeInTheDocument();
  });

  it('children remain interactive', () => {
    const onClick = vi.fn();
    render(
      <HelpSpot spotId="s1" page="p" order={1} title="T" description="D">
        <button onClick={onClick}>Click me</button>
      </HelpSpot>
    );
    fireEvent.click(screen.getByRole('button', { name: 'Click me' }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('shows tooltip on hover when helpMode=true', () => {
    mockCtx = makeContext({ helpMode: true });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(
      <HelpSpot spotId="s1" page="p" order={1} title="My Title" description="My Desc">
        <div>Content</div>
      </HelpSpot>
    );

    const wrapper = screen.getByTestId('help-spot-s1');
    fireEvent.mouseEnter(wrapper);

    expect(screen.getByRole('tooltip')).toBeInTheDocument();
    expect(screen.getByText('My Title')).toBeInTheDocument();
    expect(screen.getByText('My Desc')).toBeInTheDocument();
  });

  it('hides tooltip on mouseLeave', () => {
    mockCtx = makeContext({ helpMode: true });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(
      <HelpSpot spotId="s1" page="p" order={1} title="T" description="D">
        <div>Content</div>
      </HelpSpot>
    );

    const wrapper = screen.getByTestId('help-spot-s1');
    fireEvent.mouseEnter(wrapper);
    expect(screen.getByRole('tooltip')).toBeInTheDocument();

    fireEvent.mouseLeave(wrapper);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('shows highlight outline when helpMode=true', () => {
    mockCtx = makeContext({ helpMode: true });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(
      <HelpSpot spotId="s1" page="p" order={1} title="T" description="D">
        <div>Content</div>
      </HelpSpot>
    );

    const wrapper = screen.getByTestId('help-spot-s1');
    expect(wrapper.className).toContain('help-spot-highlight');
  });

  it('suppresses tooltip during onboarding (overlay handles it)', () => {
    mockCtx = makeContext({ helpMode: true, onboardingActive: true, activeSpotId: 's1' });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(
      <HelpSpot spotId="s1" page="p" order={1} title="Active Title" description="Active Desc">
        <div>Content</div>
      </HelpSpot>
    );

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('suppresses hover tooltip for all spots during onboarding', () => {
    mockCtx = makeContext({ helpMode: true, onboardingActive: true, activeSpotId: 'other' });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(
      <HelpSpot spotId="s1" page="p" order={1} title="T" description="D">
        <div>Content</div>
      </HelpSpot>
    );

    const wrapper = screen.getByTestId('help-spot-s1');
    fireEvent.mouseEnter(wrapper);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('tooltip has role="tooltip" and aria-live="polite"', () => {
    mockCtx = makeContext({ helpMode: true });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(
      <HelpSpot spotId="s1" page="p" order={1} title="T" description="D">
        <div>Content</div>
      </HelpSpot>
    );

    const wrapper = screen.getByTestId('help-spot-s1');
    fireEvent.mouseEnter(wrapper);
    const tooltip = screen.getByRole('tooltip');
    expect(tooltip).toHaveAttribute('aria-live', 'polite');
  });

  it('no extra highlight DOM when help inactive', () => {
    render(
      <HelpSpot spotId="s1" page="p" order={1} title="T" description="D">
        <div>Content</div>
      </HelpSpot>
    );

    const wrapper = screen.getByTestId('help-spot-s1');
    expect(wrapper.className).not.toContain('help-spot-highlight');
  });

  it('has data-help-spot attribute', () => {
    render(
      <HelpSpot spotId="s1" page="p" order={1} title="T" description="D">
        <div>Content</div>
      </HelpSpot>
    );

    expect(screen.getByTestId('help-spot-s1')).toHaveAttribute('data-help-spot', 's1');
  });

  it('calls registerSpot on mount', () => {
    const registerSpy = vi.fn(() => vi.fn());
    mockCtx = makeContext({ registerSpot: registerSpy });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(
      <HelpSpot spotId="s1" page="p" order={1} title="T" description="D">
        <div>Content</div>
      </HelpSpot>
    );

    expect(registerSpy).toHaveBeenCalledWith(
      expect.objectContaining({ id: 's1', page: 'p', order: 1, title: 'T', description: 'D' })
    );
  });

  it('uses display:contents wrapper when help is not active to avoid layout disruption', () => {
    render(
      <HelpSpot spotId="s1" page="p" order={1} title="T" description="D">
        <div>Content</div>
      </HelpSpot>
    );

    const wrapper = screen.getByTestId('help-spot-s1');
    expect(wrapper.style.display).toBe('contents');
  });

  it('tooltip uses help-tooltip class for theme-aware styling', () => {
    mockCtx = makeContext({ helpMode: true });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(
      <HelpSpot spotId="s1" page="p" order={1} title="T" description="D">
        <div>Content</div>
      </HelpSpot>
    );

    const wrapper = screen.getByTestId('help-spot-s1');
    fireEvent.mouseEnter(wrapper);
    const tooltip = screen.getByRole('tooltip');
    expect(tooltip.className).toContain('help-tooltip');
  });
});
