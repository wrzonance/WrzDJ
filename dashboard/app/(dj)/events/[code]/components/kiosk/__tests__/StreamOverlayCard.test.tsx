import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StreamOverlayCard } from '../StreamOverlayCard';

describe('StreamOverlayCard', () => {
  const originalClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');

  afterEach(() => {
    vi.useRealTimers();
    if (originalClipboard) Object.defineProperty(navigator, 'clipboard', originalClipboard);
    else Reflect.deleteProperty(navigator, 'clipboard');
  });

  it('keeps the copied confirmation visible for two seconds after the latest copy', async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    render(<StreamOverlayCard joinCode="JOIN7" />);

    expect(screen.getByRole('link', { name: 'Stream Overlay' })).toHaveAttribute(
      'href',
      '/e/JOIN7/overlay',
    );

    const copyButton = screen.getByRole('button', { name: 'Copy URL' });
    await act(async () => {
      fireEvent.click(copyButton);
      await Promise.resolve();
    });
    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/e/JOIN7/overlay`);
    expect(screen.getByRole('button', { name: 'Copied!' })).toBeInTheDocument();

    await act(async () => { vi.advanceTimersByTime(1900); });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copied!' }));
      await Promise.resolve();
    });
    await act(async () => { vi.advanceTimersByTime(100); });

    expect(screen.getByRole('button', { name: 'Copied!' })).toBeInTheDocument();
    await act(async () => { vi.advanceTimersByTime(1900); });
    expect(screen.getByRole('button', { name: 'Copy URL' })).toBeInTheDocument();
  });
});
