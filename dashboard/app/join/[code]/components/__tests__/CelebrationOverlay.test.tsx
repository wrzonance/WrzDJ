import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import CelebrationOverlay from '../CelebrationOverlay';

const song = { title: 'Strobe', artist: 'deadmau5', artwork_url: 'https://example.test/art.jpg' };

describe('CelebrationOverlay', () => {
  afterEach(() => vi.useRealTimers());

  it('shows the playing track and dismisses when tapped', () => {
    const onClose = vi.fn();
    render(<CelebrationOverlay song={song} onClose={onClose} />);

    expect(screen.getByRole('dialog', { name: 'Your song is playing' })).toBeInTheDocument();
    expect(screen.getByText('Strobe')).toBeInTheDocument();
    expect(screen.getByText('deadmau5')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('dialog', { name: 'Your song is playing' }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('auto-dismisses after eight seconds and cancels the timer when dismissed by its owner', () => {
    vi.useFakeTimers();
    const onClose = vi.fn();
    const { rerender } = render(<CelebrationOverlay song={song} onClose={onClose} />);

    act(() => vi.advanceTimersByTime(7_999));
    expect(onClose).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(1));
    expect(onClose).toHaveBeenCalledOnce();

    rerender(<CelebrationOverlay song={song} onClose={onClose} />);
    rerender(<CelebrationOverlay song={null} onClose={onClose} />);
    act(() => vi.advanceTimersByTime(8_000));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('does not render an overlay when no song is being celebrated', () => {
    render(<CelebrationOverlay song={null} onClose={vi.fn()} />);

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
