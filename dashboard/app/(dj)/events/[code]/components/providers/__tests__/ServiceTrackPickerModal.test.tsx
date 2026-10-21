import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ServiceTrackPickerModal } from '../ServiceTrackPickerModal';
import type { BeatportSearchResult, TidalSearchResult } from '@/lib/api/types';

const tidalTrack: TidalSearchResult = {
  album: 'Blue Album',
  artist: 'DJ Blue',
  bpm: 122,
  cover_url: null,
  duration_seconds: 220,
  explicit: false,
  isrc: null,
  key: '7A',
  popularity: 80,
  tidal_url: null,
  title: 'Blue Track',
  track_id: 'tidal-123',
  version: null,
};
const beatportTrack: BeatportSearchResult = {
  artist: 'DJ Green',
  beatport_url: null,
  bpm: 126,
  cover_url: null,
  duration_seconds: 240,
  genre: 'Tech House',
  key: '9A',
  label: 'Green Label',
  mix_name: 'Extended Mix',
  release_date: null,
  title: 'Green Track',
  track_id: 'beatport-456',
};

function baseProps() {
  return {
    requestId: 42,
    searchQuery: 'track',
    tidalResults: [] as TidalSearchResult[],
    beatportResults: [] as BeatportSearchResult[],
    searching: false,
    linking: false,
    onSearchQueryChange: vi.fn(),
    onSearch: vi.fn(),
    onSelectTrack: vi.fn(),
    onCancel: vi.fn(),
  };
}

describe('ServiceTrackPickerModal', () => {
  it('uses the active provider label and forwards query/search actions', () => {
    const props = baseProps();
    render(<ServiceTrackPickerModal service="tidal" {...props} />);

    expect(screen.getByRole('heading', { name: 'Link Tidal Track' })).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText('Search Tidal...'), { target: { value: 'new query' } });
    fireEvent.keyDown(screen.getByPlaceholderText('Search Tidal...'), { key: 'Enter' });
    expect(props.onSearchQueryChange).toHaveBeenCalledWith('new query');
    expect(props.onSearch).toHaveBeenCalledOnce();
  });

  it('selects the chosen Tidal track for the associated request', () => {
    const props = baseProps();
    render(<ServiceTrackPickerModal service="tidal" {...props} tidalResults={[tidalTrack]} />);

    expect(screen.getByText('Blue Album')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Blue Track'));

    expect(props.onSelectTrack).toHaveBeenCalledWith(42, 'tidal-123');
  });

  it('shows Beatport track details and disables cancel while linking', () => {
    const props = baseProps();
    render(
      <ServiceTrackPickerModal service="beatport" {...props} linking beatportResults={[beatportTrack]} />,
    );

    expect(screen.getByRole('heading', { name: 'Link Beatport Track' })).toBeInTheDocument();
    expect(screen.getByText(/Green Track/)).toBeInTheDocument();
    expect(screen.getByText('Green Label')).toBeInTheDocument();
    expect(screen.getByText('126 BPM')).toBeInTheDocument();
    fireEvent.click(screen.getByText(/Green Track/));
    expect(props.onSelectTrack).toHaveBeenCalledWith(42, 'beatport-456');
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
  });
});
