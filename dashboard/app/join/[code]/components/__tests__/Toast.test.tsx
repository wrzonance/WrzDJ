import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Toast from '../Toast';

describe('Toast', () => {
  afterEach(() => vi.useRealTimers());

  it('announces its message and dismisses after four seconds', () => {
    vi.useFakeTimers();
    const onDismiss = vi.fn();
    render(<Toast message="Request added" type="success" onDismiss={onDismiss} />);

    expect(screen.getByRole('alert')).toHaveTextContent('Request added');
    act(() => vi.advanceTimersByTime(3_999));
    expect(onDismiss).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(1));
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it('also dismisses immediately when the guest taps it', () => {
    const onDismiss = vi.fn();
    render(<Toast message="Profile saved" type="info" onDismiss={onDismiss} />);

    fireEvent.click(screen.getByRole('alert'));

    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it('cancels its auto-dismiss after unmount', () => {
    vi.useFakeTimers();
    const onDismiss = vi.fn();
    const { unmount } = render(<Toast message="Saved" type="success" onDismiss={onDismiss} />);

    unmount();
    act(() => vi.advanceTimersByTime(4_000));

    expect(onDismiss).not.toHaveBeenCalled();
  });
});
