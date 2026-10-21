import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { PlayHistoryItem } from '@/lib/api';
import { PlayHistorySection } from '../PlayHistorySection';

const item: PlayHistoryItem = {
  id: 12,
  album: 'Night Drive',
  album_art_url: null,
  artist: 'DJ Example',
  ended_at: null,
  matched_request_id: 44,
  play_order: 1,
  source: 'live',
  spotify_uri: null,
  started_at: '2026-10-19T20:00:00Z',
  title: 'Midnight Signal',
};

describe('PlayHistorySection', () => {
  it('hides the section when there are no played tracks', () => {
    const { container } = render(
      <PlayHistorySection items={[]} total={0} exporting={false} onExport={vi.fn()} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it('exposes an accessible toggle and exports the expanded track history', () => {
    const onExport = vi.fn();
    render(
      <PlayHistorySection items={[item]} total={1} exporting={false} onExport={onExport} />,
    );

    const toggle = screen.getByRole('button', { name: /play history.*1 track/i });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Midnight Signal')).not.toBeInTheDocument();

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Midnight Signal')).toBeInTheDocument();
    expect(screen.getByText('Live')).toBeInTheDocument();
    expect(screen.getByText('Requested')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Export Play History' }));
    expect(onExport).toHaveBeenCalledOnce();
  });

  it('disables export while a history download is in progress', () => {
    render(
      <PlayHistorySection items={[item]} total={1} exporting onExport={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /play history/i }));

    expect(screen.getByRole('button', { name: 'Exporting...' })).toBeDisabled();
  });
});
