import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import StreamOverlayPage from '../page';
import { api } from '@/lib/api';
import type { KioskDisplay, NowPlayingInfo } from '@/lib/api/types';

vi.mock('next/navigation', () => ({ useParams: () => ({ code: 'PARTY' }) }));
vi.mock('@/lib/use-event-stream', () => ({ useEventStream: vi.fn() }));

const display = (overrides: Partial<KioskDisplay> = {}): KioskDisplay => ({
  accepted_queue: [
    { id: 2, title: 'Next Song', artist: 'Next Artist', artwork_url: null, vote_count: 2,
      bpm: null, genre: null, musical_key: null, nickname: null, requester_verified: false },
    { id: 3, title: 'Later Song', artist: 'Later Artist', artwork_url: null, vote_count: 0,
      bpm: null, genre: null, musical_key: null, nickname: null, requester_verified: false },
  ],
  accepted_queue_total: 2,
  banner_colors: null,
  banner_kiosk_url: null,
  banner_url: null,
  event: {} as KioskDisplay['event'],
  kiosk_display_only: false,
  now_playing: null,
  now_playing_hidden: false,
  qr_join_url: 'https://example.test/join/PARTY',
  requests_open: true,
  updated_at: '2026-01-01T00:00:00Z',
  ...overrides,
});

const nowPlaying: NowPlayingInfo = {
  album: 'Album',
  album_art_url: 'https://example.test/cover.jpg',
  artist: 'Current Artist',
  bridge_connected: true,
  matched_request_id: null,
  source: 'spotify',
  spotify_uri: null,
  started_at: '2026-01-01T00:00:00Z',
  title: 'Current Song',
};

describe('stream overlay route', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('shows the live track and at most five accepted requests', async () => {
    const acceptedQueue = Array.from({ length: 7 }, (_, index) => ({
      id: index + 1,
      title: `Queue Song ${index + 1}`,
      artist: `Artist ${index + 1}`,
      artwork_url: null,
      vote_count: index,
      bpm: null,
      genre: null,
      musical_key: null,
      nickname: null,
      requester_verified: false,
    }));
    vi.spyOn(api, 'getKioskDisplay').mockResolvedValue(display({ accepted_queue: acceptedQueue }));
    vi.spyOn(api, 'getNowPlaying').mockResolvedValue(nowPlaying);

    render(<StreamOverlayPage />);

    expect(await screen.findByText('Current Song')).toBeInTheDocument();
    expect(screen.getByText('LIVE')).toBeInTheDocument();
    expect(screen.getByText('IN QUEUE')).toBeInTheDocument();
    expect(screen.getByText('Queue Song 5')).toBeInTheDocument();
    expect(screen.queryByText('Queue Song 6')).not.toBeInTheDocument();
  });

  it('respects the event setting that hides now playing while keeping the queue visible', async () => {
    vi.spyOn(api, 'getKioskDisplay').mockResolvedValue(display({ now_playing_hidden: true }));
    vi.spyOn(api, 'getNowPlaying').mockResolvedValue(nowPlaying);

    render(<StreamOverlayPage />);

    expect(await screen.findByText('IN QUEUE')).toBeInTheDocument();
    expect(screen.queryByText('Current Song')).not.toBeInTheDocument();
    expect(screen.getByText('Next Song')).toBeInTheDocument();
  });
});
