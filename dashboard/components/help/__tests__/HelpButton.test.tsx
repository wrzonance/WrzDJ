import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { HelpButton } from '../HelpButton';
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
    hasSeenPage: vi.fn(() => false),
    ...overrides,
  };
}

let mockCtx: HelpContextValue;

beforeEach(() => {
  mockCtx = makeContext();
  vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);
});

describe('HelpButton', () => {
  it('renders "?" with aria-label', () => {
    render(<HelpButton page="events" />);
    const btn = screen.getByRole('button', { name: 'Toggle help mode' });
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveTextContent('?');
  });

  it('aria-pressed reflects helpMode state', () => {
    mockCtx = makeContext({ helpMode: true });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<HelpButton page="events" />);
    expect(screen.getByRole('button', { name: 'Toggle help mode' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('aria-pressed is false when helpMode is off', () => {
    render(<HelpButton page="events" />);
    expect(screen.getByRole('button', { name: 'Toggle help mode' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('click calls toggleHelpMode', () => {
    const toggle = vi.fn();
    mockCtx = makeContext({ toggleHelpMode: toggle });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<HelpButton page="events" />);
    fireEvent.click(screen.getByRole('button', { name: 'Toggle help mode' }));
    expect(toggle).toHaveBeenCalledTimes(1);
  });

  it('has active visual class when helpMode=true', () => {
    mockCtx = makeContext({ helpMode: true });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<HelpButton page="events" />);
    expect(screen.getByRole('button', { name: 'Toggle help mode' }).className).toContain('help-btn-active');
  });

  it('does not toggle during onboarding', () => {
    const toggle = vi.fn();
    mockCtx = makeContext({ onboardingActive: true, helpMode: true, toggleHelpMode: toggle });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<HelpButton page="events" />);
    fireEvent.click(screen.getByRole('button', { name: 'Toggle help mode' }));
    expect(toggle).not.toHaveBeenCalled();
  });

  it('shows "Start Tour" when helpMode=true and not onboarding', () => {
    mockCtx = makeContext({ helpMode: true });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<HelpButton page="events" />);
    expect(screen.getByText('Start Tour')).toBeInTheDocument();
  });

  it('"Start Tour" calls startOnboarding with page', () => {
    const startFn = vi.fn();
    mockCtx = makeContext({ helpMode: true, startOnboarding: startFn });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<HelpButton page="my-page" />);
    fireEvent.click(screen.getByText('Start Tour'));
    expect(startFn).toHaveBeenCalledWith('my-page');
  });

  it('renders in normal flow inside a help-controls group (#863)', () => {
    render(<HelpButton page="events" />);
    const container = screen.getByRole('button', { name: 'Toggle help mode' }).parentElement;
    expect(container?.className).toBe('help-controls');
  });

  it('places "Start Tour" before the ? button so the row grows leftward', () => {
    mockCtx = makeContext({ helpMode: true });
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(mockCtx);

    render(<HelpButton page="events" />);
    const buttons = screen.getAllByRole('button').map((b) => b.textContent);
    expect(buttons).toEqual(['Start Tour', '?']);
  });

  it('renders nothing when wrzdj-help-disabled flag is set', () => {
    const originalStorage = globalThis.localStorage;
    const mockStorage = { getItem: vi.fn((key: string) => key === 'wrzdj-help-disabled' ? '1' : null) };
    Object.defineProperty(globalThis, 'localStorage', { value: mockStorage, writable: true, configurable: true });
    try {
      render(<HelpButton page="events" />);
      expect(screen.queryByRole('button', { name: 'Toggle help mode' })).not.toBeInTheDocument();
    } finally {
      Object.defineProperty(globalThis, 'localStorage', { value: originalStorage, writable: true, configurable: true });
    }
  });
});
