import { act, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Sparks from '../Sparks';

describe('Sparks lifecycle', () => {
  afterEach(() => vi.useRealTimers());

  it('clears the animation when its owning request is replaced', () => {
    // Regression for baseline 57cfcdc6867f: canceling a spark before its timer leaves it active.
    vi.useFakeTimers();
    const onDone = vi.fn();
    const { container, rerender } = render(
      <Sparks accent="#fff" accent2="#aaa" fire onDone={onDone} />,
    );

    expect(container.querySelectorAll('span')).toHaveLength(14);
    rerender(<Sparks accent="#fff" accent2="#aaa" fire={false} onDone={onDone} />);

    expect(container.querySelectorAll('span')).toHaveLength(0);
    act(() => vi.advanceTimersByTime(900));
    expect(onDone).not.toHaveBeenCalled();
  });

  it('finishes the animation and notifies its owner after 900ms', () => {
    vi.useFakeTimers();
    const onDone = vi.fn();
    const { container } = render(
      <Sparks accent="#fff" accent2="#aaa" fire onDone={onDone} />,
    );

    act(() => vi.advanceTimersByTime(899));
    expect(container.querySelectorAll('span')).toHaveLength(14);
    expect(onDone).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(1));
    expect(container.querySelectorAll('span')).toHaveLength(0);
    expect(onDone).toHaveBeenCalledOnce();
  });
});
