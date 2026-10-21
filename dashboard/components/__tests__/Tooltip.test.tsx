import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Tooltip } from '../Tooltip';

describe('Tooltip', () => {
  beforeEach(() => vi.useFakeTimers());

  afterEach(() => {
    cleanup();
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  it('shows content only after the configured hover delay', () => {
    render(
      <Tooltip description="Helpful detail" delay={200}>
        <button type="button">Trigger</button>
      </Tooltip>,
    );

    fireEvent.mouseEnter(screen.getByRole('button'));
    act(() => vi.advanceTimersByTime(199));
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();

    act(() => vi.advanceTimersByTime(1));
    expect(screen.getByRole('tooltip')).toHaveTextContent('Helpful detail');
  });

  it('cancels a pending show when the pointer leaves before the delay', () => {
    render(
      <Tooltip description="Helpful detail" delay={200}>
        <button type="button">Trigger</button>
      </Tooltip>,
    );

    fireEvent.mouseEnter(screen.getByRole('button'));
    act(() => vi.advanceTimersByTime(100));
    fireEvent.mouseLeave(screen.getByRole('button'));
    act(() => vi.advanceTimersByTime(200));

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('hides visible content when the pointer leaves', () => {
    render(
      <Tooltip description="Helpful detail" delay={200}>
        <button type="button">Trigger</button>
      </Tooltip>,
    );

    fireEvent.mouseEnter(screen.getByRole('button'));
    act(() => vi.advanceTimersByTime(200));
    expect(screen.getByRole('tooltip')).toBeInTheDocument();

    fireEvent.mouseLeave(screen.getByRole('button'));
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('does not render a tooltip without content', () => {
    const { container } = render(
      <Tooltip>
        <button type="button">Trigger</button>
      </Tooltip>,
    );

    fireEvent.mouseEnter(screen.getByRole('button'));
    act(() => vi.advanceTimersByTime(200));

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    expect(container).toHaveTextContent('Trigger');
  });

  // Regression for 57cfcdc: an unmounted tooltip left its delayed show callback pending.
  it('clears a pending show timer when unmounted', () => {
    const { unmount } = render(
      <Tooltip description="Helpful detail" delay={200}>
        <button type="button">Trigger</button>
      </Tooltip>,
    );

    fireEvent.mouseEnter(screen.getByRole('button'));
    expect(vi.getTimerCount()).toBe(1);

    unmount();

    expect(vi.getTimerCount()).toBe(0);
  });
});
