import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useHelpSpot } from '../useHelpSpot';
import * as HelpContext from '../HelpContext';

const mockRegisterSpot = vi.fn(() => vi.fn());

vi.spyOn(HelpContext, 'useHelp').mockReturnValue({
  helpMode: false,
  onboardingActive: false,
  currentStep: 0,
  activeSpotId: null,
  toggleHelpMode: vi.fn(),
  registerSpot: mockRegisterSpot,
  getSpotsForPage: vi.fn(() => []),
  startOnboarding: vi.fn(),
  nextStep: vi.fn(),
  prevStep: vi.fn(),
  skipOnboarding: vi.fn(),
  dismissOnboarding: vi.fn(),
  hasSeenPage: vi.fn(() => false),
});

describe('useHelpSpot', () => {
  beforeEach(() => {
    mockRegisterSpot.mockClear();
    mockRegisterSpot.mockReturnValue(vi.fn());
  });

  it('returns a ref object', () => {
    const { result } = renderHook(() =>
      useHelpSpot({ id: 'test', page: 'p', order: 1, title: 'T', description: 'D' })
    );
    expect(result.current).toHaveProperty('current');
  });

  it('calls deregister on unmount', () => {
    const deregister = vi.fn();
    mockRegisterSpot.mockReturnValue(deregister);

    const { unmount } = renderHook(() =>
      useHelpSpot({ id: 'test', page: 'p', order: 1, title: 'T', description: 'D' })
    );

    unmount();
    expect(deregister).toHaveBeenCalledTimes(1);
  });

  it('re-registers when spotId changes', () => {
    const deregister1 = vi.fn();
    const deregister2 = vi.fn();
    mockRegisterSpot.mockReturnValueOnce(deregister1).mockReturnValueOnce(deregister2);

    const { rerender } = renderHook(
      ({ id }) => useHelpSpot({ id, page: 'p', order: 1, title: 'T', description: 'D' }),
      { initialProps: { id: 'spot-a' } }
    );

    expect(mockRegisterSpot).toHaveBeenCalledTimes(1);

    rerender({ id: 'spot-b' });
    expect(deregister1).toHaveBeenCalledTimes(1);
    expect(mockRegisterSpot).toHaveBeenCalledTimes(2);
  });
});
