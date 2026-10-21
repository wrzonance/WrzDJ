import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { render, screen } from '@testing-library/react';
import React, { createRef } from 'react';
import { HelpProvider, useHelp } from '../HelpContext';
import { initSeenPages, isPageSeen, TOURS_SKIPPED } from '../seen-pages';
import type { HelpSpotConfig } from '../types';

// Mock the api module so completeOnboarding doesn't make real HTTP calls
vi.mock('@/lib/api', () => ({
  api: {
    markHelpPageSeen: vi.fn().mockResolvedValue(undefined),
  },
}));

// jsdom localStorage mock
const store: Record<string, string> = {};
const localStorageMock = {
  getItem: (key: string) => store[key] ?? null,
  setItem: (key: string, value: string) => { store[key] = value; },
  removeItem: (key: string) => { delete store[key]; },
  clear: () => { Object.keys(store).forEach((k) => delete store[k]); },
  get length() { return Object.keys(store).length; },
  key: (i: number) => Object.keys(store)[i] ?? null,
};
Object.defineProperty(window, 'localStorage', { value: localStorageMock, writable: true });

function wrapper({ children }: { children: React.ReactNode }) {
  return <HelpProvider>{children}</HelpProvider>;
}

function makeSpot(overrides: Partial<HelpSpotConfig> = {}): HelpSpotConfig {
  return {
    id: 'test-spot',
    page: 'test-page',
    order: 1,
    title: 'Test Spot',
    description: 'A test spot',
    ref: createRef<HTMLElement>(),
    ...overrides,
  };
}

describe('HelpContext', () => {
  beforeEach(() => {
    localStorageMock.clear();
    initSeenPages([]);
  });

  it('throws when useHelp is called outside provider', () => {
    // Suppress React error boundary console output
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => renderHook(() => useHelp())).toThrow(
      'useHelp must be used within a HelpProvider'
    );
    spy.mockRestore();
  });

  it('renders children', () => {
    render(
      <HelpProvider>
        <div data-testid="child">Hello</div>
      </HelpProvider>
    );
    expect(screen.getByTestId('child')).toHaveTextContent('Hello');
  });

  it('toggleHelpMode flips helpMode on and off', () => {
    const { result } = renderHook(() => useHelp(), { wrapper });
    expect(result.current.helpMode).toBe(false);

    act(() => result.current.toggleHelpMode());
    expect(result.current.helpMode).toBe(true);

    act(() => result.current.toggleHelpMode());
    expect(result.current.helpMode).toBe(false);
  });

  it('registerSpot adds a spot and getSpotsForPage returns it', () => {
    const { result } = renderHook(() => useHelp(), { wrapper });
    const spot = makeSpot();

    act(() => {
      result.current.registerSpot(spot);
    });

    const spots = result.current.getSpotsForPage('test-page');
    expect(spots).toHaveLength(1);
    expect(spots[0].id).toBe('test-spot');
  });

  it('deregister function removes the spot', () => {
    const { result } = renderHook(() => useHelp(), { wrapper });
    const spot = makeSpot();
    let deregister: () => void;

    act(() => {
      deregister = result.current.registerSpot(spot);
    });

    expect(result.current.getSpotsForPage('test-page')).toHaveLength(1);

    act(() => {
      deregister();
    });

    expect(result.current.getSpotsForPage('test-page')).toHaveLength(0);
  });

  it('getSpotsForPage filters by page and sorts by order', () => {
    const { result } = renderHook(() => useHelp(), { wrapper });

    act(() => {
      result.current.registerSpot(makeSpot({ id: 'b', page: 'p1', order: 2 }));
      result.current.registerSpot(makeSpot({ id: 'a', page: 'p1', order: 1 }));
      result.current.registerSpot(makeSpot({ id: 'c', page: 'p2', order: 1 }));
    });

    const p1Spots = result.current.getSpotsForPage('p1');
    expect(p1Spots).toHaveLength(2);
    expect(p1Spots[0].id).toBe('a');
    expect(p1Spots[1].id).toBe('b');

    const p2Spots = result.current.getSpotsForPage('p2');
    expect(p2Spots).toHaveLength(1);
    expect(p2Spots[0].id).toBe('c');
  });

  it('startOnboarding sets onboardingActive, currentStep=0, and activeSpotId', () => {
    const { result } = renderHook(() => useHelp(), { wrapper });
    const spot = makeSpot({ id: 'first', page: 'demo', order: 1 });

    act(() => {
      result.current.registerSpot(spot);
    });

    act(() => {
      result.current.startOnboarding('demo');
    });

    expect(result.current.onboardingActive).toBe(true);
    expect(result.current.currentStep).toBe(0);
    expect(result.current.activeSpotId).toBe('first');
  });

  it('nextStep advances to the next spot', () => {
    const { result } = renderHook(() => useHelp(), { wrapper });

    act(() => {
      result.current.registerSpot(makeSpot({ id: 's1', page: 'p', order: 1 }));
      result.current.registerSpot(makeSpot({ id: 's2', page: 'p', order: 2 }));
    });

    act(() => result.current.startOnboarding('p'));
    expect(result.current.activeSpotId).toBe('s1');

    act(() => result.current.nextStep());
    expect(result.current.currentStep).toBe(1);
    expect(result.current.activeSpotId).toBe('s2');
  });

  it('prevStep goes back to the previous spot', () => {
    const { result } = renderHook(() => useHelp(), { wrapper });

    act(() => {
      result.current.registerSpot(makeSpot({ id: 's1', page: 'p', order: 1 }));
      result.current.registerSpot(makeSpot({ id: 's2', page: 'p', order: 2 }));
    });

    act(() => result.current.startOnboarding('p'));
    act(() => result.current.nextStep());
    expect(result.current.activeSpotId).toBe('s2');

    act(() => result.current.prevStep());
    expect(result.current.currentStep).toBe(0);
    expect(result.current.activeSpotId).toBe('s1');
  });

  it('prevStep does nothing at step 0', () => {
    const { result } = renderHook(() => useHelp(), { wrapper });

    act(() => {
      result.current.registerSpot(makeSpot({ id: 's1', page: 'p', order: 1 }));
    });

    act(() => result.current.startOnboarding('p'));
    act(() => result.current.prevStep());
    expect(result.current.currentStep).toBe(0);
    expect(result.current.activeSpotId).toBe('s1');
  });

  it('skipOnboarding resets state and opts out of tours on every page (#863)', async () => {
    const { api: mockApi } = await import('@/lib/api');
    const { result } = renderHook(() => useHelp(), { wrapper });

    act(() => {
      result.current.registerSpot(makeSpot({ id: 's1', page: 'mypage', order: 1 }));
    });

    act(() => result.current.startOnboarding('mypage'));
    expect(result.current.onboardingActive).toBe(true);

    act(() => result.current.skipOnboarding());
    expect(result.current.onboardingActive).toBe(false);
    expect(result.current.activeSpotId).toBeNull();
    expect(window.localStorage.getItem(`wrzdj-help-seen-${TOURS_SKIPPED}`)).toBe('1');
    expect(window.localStorage.getItem('wrzdj-help-seen-mypage')).toBeNull();
    expect(mockApi.markHelpPageSeen).toHaveBeenCalledWith(TOURS_SKIPPED);
    expect(result.current.hasSeenPage('mypage')).toBe(true);
    expect(result.current.hasSeenPage('some-other-page')).toBe(true);
  });

  it('hasSeenPage honours a server-side tours-skipped marker (#863)', () => {
    initSeenPages([TOURS_SKIPPED]);
    const { result } = renderHook(() => useHelp(), { wrapper });
    expect(result.current.hasSeenPage('dashboard')).toBe(true);
    expect(result.current.hasSeenPage('admin-users')).toBe(true);
  });

  it('completing a tour marks only that page as seen', () => {
    const { result } = renderHook(() => useHelp(), { wrapper });

    act(() => {
      result.current.registerSpot(makeSpot({ id: 's1', page: 'done-page', order: 1 }));
    });

    act(() => result.current.startOnboarding('done-page'));
    act(() => result.current.nextStep());

    expect(result.current.hasSeenPage('done-page')).toBe(true);
    expect(result.current.hasSeenPage('another-page')).toBe(false);
  });

  it('restores help mode to its pre-tour state when the tour ends (#863)', () => {
    const { result } = renderHook(() => useHelp(), { wrapper });

    act(() => {
      result.current.registerSpot(makeSpot({ id: 's1', page: 'p', order: 1 }));
    });

    // Auto-started tour: help mode was off, so it goes back off.
    act(() => result.current.startOnboarding('p'));
    expect(result.current.helpMode).toBe(true);
    act(() => result.current.skipOnboarding());
    expect(result.current.helpMode).toBe(false);

    // Tour started from help mode: help mode stays on afterwards.
    act(() => result.current.toggleHelpMode());
    act(() => result.current.startOnboarding('p'));
    act(() => result.current.nextStep());
    expect(result.current.onboardingActive).toBe(false);
    expect(result.current.helpMode).toBe(true);
  });

  it('hasSeenPage reads localStorage', () => {
    const { result } = renderHook(() => useHelp(), { wrapper });

    expect(result.current.hasSeenPage('new-page')).toBe(false);

    window.localStorage.setItem('wrzdj-help-seen-new-page', '1');
    expect(result.current.hasSeenPage('new-page')).toBe(true);
  });

  it('nextStep past last step auto-completes onboarding', () => {
    const { result } = renderHook(() => useHelp(), { wrapper });

    act(() => {
      result.current.registerSpot(makeSpot({ id: 's1', page: 'pg', order: 1 }));
    });

    act(() => result.current.startOnboarding('pg'));
    expect(result.current.onboardingActive).toBe(true);

    act(() => result.current.nextStep());
    expect(result.current.onboardingActive).toBe(false);
    expect(result.current.activeSpotId).toBeNull();
    expect(window.localStorage.getItem('wrzdj-help-seen-pg')).toBe('1');
  });

  it('startOnboarding does nothing when no spots exist for the page', () => {
    const { result } = renderHook(() => useHelp(), { wrapper });

    act(() => result.current.startOnboarding('empty-page'));
    expect(result.current.onboardingActive).toBe(false);
  });

  it('hasSeenPage returns true for server-initialized pages', () => {
    initSeenPages(['admin-overview', 'events']);
    const { result } = renderHook(() => useHelp(), { wrapper });

    expect(result.current.hasSeenPage('admin-overview')).toBe(true);
    expect(result.current.hasSeenPage('events')).toBe(true);
    expect(result.current.hasSeenPage('unknown-page')).toBe(false);
  });

  it('completeOnboarding updates seen-pages module', async () => {
    const { api: mockApi } = await import('@/lib/api');
    const { result } = renderHook(() => useHelp(), { wrapper });

    act(() => {
      result.current.registerSpot(makeSpot({ id: 's1', page: 'demo', order: 1 }));
    });

    act(() => result.current.startOnboarding('demo'));
    act(() => result.current.nextStep()); // completes (single step)

    expect(isPageSeen('demo')).toBe(true);
    expect(mockApi.markHelpPageSeen).toHaveBeenCalledWith('demo');
  });
});

describe('seen-pages module', () => {
  beforeEach(() => {
    initSeenPages([]);
  });

  it('initSeenPages populates the set', () => {
    initSeenPages(['page-a', 'page-b']);
    expect(isPageSeen('page-a')).toBe(true);
    expect(isPageSeen('page-b')).toBe(true);
    expect(isPageSeen('page-c')).toBe(false);
  });

  it('initSeenPages replaces previous state', () => {
    initSeenPages(['old-page']);
    expect(isPageSeen('old-page')).toBe(true);

    initSeenPages(['new-page']);
    expect(isPageSeen('old-page')).toBe(false);
    expect(isPageSeen('new-page')).toBe(true);
  });
});

describe('seen-pages browser fallback ownership (#863 review)', () => {
  beforeEach(() => {
    localStorageMock.clear();
    initSeenPages([]);
  });

  it('purges another account\'s fallback keys when a different user signs in', () => {
    initSeenPages([], 1);
    window.localStorage.setItem(`wrzdj-help-seen-${TOURS_SKIPPED}`, '1');
    window.localStorage.setItem('wrzdj-help-seen-dashboard', '1');
    initSeenPages([], 1);
    expect(window.localStorage.getItem(`wrzdj-help-seen-${TOURS_SKIPPED}`)).toBe('1');

    initSeenPages([], 2);
    expect(window.localStorage.getItem(`wrzdj-help-seen-${TOURS_SKIPPED}`)).toBeNull();
    expect(window.localStorage.getItem('wrzdj-help-seen-dashboard')).toBeNull();

    const { result } = renderHook(() => useHelp(), { wrapper });
    expect(result.current.hasSeenPage('dashboard')).toBe(false);
  });

  it('purges keys left by the pre-ownership scheme on the first claim', () => {
    window.localStorage.setItem('wrzdj-help-seen-dashboard', '1');
    initSeenPages([], 3);
    expect(window.localStorage.getItem('wrzdj-help-seen-dashboard')).toBeNull();
  });

  it('keeps the fallback for the same account across sign-ins', () => {
    initSeenPages([], 7);
    window.localStorage.setItem(`wrzdj-help-seen-${TOURS_SKIPPED}`, '1');
    initSeenPages([], 7);
    expect(window.localStorage.getItem(`wrzdj-help-seen-${TOURS_SKIPPED}`)).toBe('1');
  });
});
