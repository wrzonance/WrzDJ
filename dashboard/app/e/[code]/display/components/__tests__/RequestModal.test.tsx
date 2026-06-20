import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { RequestModal } from '../RequestModal';

// Track mock instances so tests can inspect setOptions calls
const mockKeyboardInstances: Array<{
  setOptions: ReturnType<typeof vi.fn>;
  setInput: ReturnType<typeof vi.fn>;
  destroy: ReturnType<typeof vi.fn>;
}> = [];

vi.mock('simple-keyboard', () => ({
  default: class MockKeyboard {
    setOptions = vi.fn();
    setInput = vi.fn();
    destroy = vi.fn();
    constructor() {
      mockKeyboardInstances.push(this);
    }
  },
}));

vi.mock('@/lib/api', () => ({
  api: {
    search: vi.fn(),
    eventSearch: vi.fn(),
    submitRequest: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.name = 'ApiError';
      this.status = status;
    }
  },
}));

import { api, ApiError } from '@/lib/api';

const mockOnClose = vi.fn();
const mockOnRequestsClosed = vi.fn();

function renderModal() {
  return render(
    <RequestModal
      code="TEST01"
      onClose={mockOnClose}
      onRequestsClosed={mockOnRequestsClosed}
    />
  );
}

const mockResults = [
  {
    title: 'Strobe', artist: 'deadmau5', spotify_id: 'sp1',
    url: 'https://open.spotify.com/track/1', album_art: 'https://example.com/art.jpg',
    album: 'For Lack of a Better Name', popularity: 80, preview_url: null,
    source: 'spotify' as const, genre: null, bpm: null, key: null, isrc: null,
  },
  {
    title: 'Levels', artist: 'Avicii', spotify_id: 'sp2',
    url: null, album_art: null,
    album: null, popularity: 90, preview_url: null,
    source: 'spotify' as const, genre: null, bpm: null, key: null, isrc: null,
  },
];

describe('RequestModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    mockKeyboardInstances.length = 0;
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders search form initially', () => {
    renderModal();
    expect(screen.getByText('Request a Song')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search for a song...')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Search' })).toBeInTheDocument();
  });

  it('does not search with empty query', async () => {
    renderModal();
    await act(async () => {
      fireEvent.submit(screen.getByRole('button', { name: 'Search' }));
    });
    expect(api.eventSearch).not.toHaveBeenCalled();
  });

  it('searches and displays results', async () => {
    vi.mocked(api.eventSearch).mockResolvedValue(mockResults);

    renderModal();

    fireEvent.change(screen.getByPlaceholderText('Search for a song...'), {
      target: { value: 'strobe' },
    });
    await act(async () => {
      fireEvent.submit(screen.getByRole('button', { name: 'Search' }));
    });

    expect(api.eventSearch).toHaveBeenCalledWith('TEST01', 'strobe');
    expect(screen.getByText('Strobe')).toBeInTheDocument();
    expect(screen.getByText('deadmau5')).toBeInTheDocument();
    expect(screen.getByText('Levels')).toBeInTheDocument();
  });

  // Regression: the kiosk is an un-authenticated guest device. It previously
  // called api.search() (the DJ-only /api/search, which 401s without a JWT),
  // so search silently returned nothing. It must call the PUBLIC event endpoint
  // (api.eventSearch) with the event code, and never the DJ-only api.search.
  it('searches via the public event endpoint, not the DJ-only endpoint', async () => {
    vi.mocked(api.eventSearch).mockResolvedValue(mockResults);

    renderModal();

    fireEvent.change(screen.getByPlaceholderText('Search for a song...'), {
      target: { value: 'strobe' },
    });
    await act(async () => {
      fireEvent.submit(screen.getByRole('button', { name: 'Search' }));
    });

    expect(api.eventSearch).toHaveBeenCalledWith('TEST01', 'strobe');
    expect(api.search).not.toHaveBeenCalled();
  });

  it('shows an error message when search fails', async () => {
    vi.mocked(api.eventSearch).mockRejectedValue(new Error('Network error'));

    renderModal();

    fireEvent.change(screen.getByPlaceholderText('Search for a song...'), {
      target: { value: 'test' },
    });
    await act(async () => {
      fireEvent.submit(screen.getByRole('button', { name: 'Search' }));
    });

    // Should not crash, no results, and a visible error (no longer silent)
    expect(screen.queryByText('Strobe')).not.toBeInTheDocument();
    expect(screen.getByText('Search failed — please try again.')).toBeInTheDocument();
  });

  it('shows "No songs found" when search returns no results', async () => {
    vi.mocked(api.eventSearch).mockResolvedValue([]);

    renderModal();

    fireEvent.change(screen.getByPlaceholderText('Search for a song...'), {
      target: { value: 'asdfqwer' },
    });
    await act(async () => {
      fireEvent.submit(screen.getByRole('button', { name: 'Search' }));
    });

    expect(screen.getByText('No songs found')).toBeInTheDocument();
  });

  it('selects a song and shows confirmation view', async () => {
    vi.mocked(api.eventSearch).mockResolvedValue(mockResults);

    renderModal();

    fireEvent.change(screen.getByPlaceholderText('Search for a song...'), {
      target: { value: 'strobe' },
    });
    await act(async () => {
      fireEvent.submit(screen.getByRole('button', { name: 'Search' }));
    });

    // Click on a result
    fireEvent.click(screen.getByText('Strobe'));

    expect(screen.getByText('Confirm Request')).toBeInTheDocument();
    expect(screen.getByText('Strobe')).toBeInTheDocument();
    expect(screen.getByText('deadmau5')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Submit Request' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Back' })).toBeInTheDocument();
  });

  it('goes back from confirmation to search results', async () => {
    vi.mocked(api.eventSearch).mockResolvedValue(mockResults);

    renderModal();

    fireEvent.change(screen.getByPlaceholderText('Search for a song...'), {
      target: { value: 'strobe' },
    });
    await act(async () => {
      fireEvent.submit(screen.getByRole('button', { name: 'Search' }));
    });

    fireEvent.click(screen.getByText('Strobe'));
    expect(screen.getByText('Confirm Request')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByText('Request a Song')).toBeInTheDocument();
  });

  it('submits request and shows success message', async () => {
    vi.mocked(api.eventSearch).mockResolvedValue(mockResults);
    vi.mocked(api.submitRequest).mockResolvedValue({
      id: 1,
      artist: 'deadmau5',
      song_title: 'Strobe',
      status: 'new',
      is_duplicate: false,
      vote_count: 0,
    } as never);

    renderModal();

    fireEvent.change(screen.getByPlaceholderText('Search for a song...'), {
      target: { value: 'strobe' },
    });
    await act(async () => {
      fireEvent.submit(screen.getByRole('button', { name: 'Search' }));
    });

    fireEvent.click(screen.getByText('Strobe'));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Submit Request' }));
    });

    expect(screen.getByText('Request Submitted!')).toBeInTheDocument();
  });

  it('shows "Vote Added!" for duplicate requests', async () => {
    vi.mocked(api.eventSearch).mockResolvedValue(mockResults);
    vi.mocked(api.submitRequest).mockResolvedValue({
      id: 1,
      artist: 'deadmau5',
      song_title: 'Strobe',
      status: 'new',
      is_duplicate: true,
      vote_count: 3,
    } as never);

    renderModal();

    fireEvent.change(screen.getByPlaceholderText('Search for a song...'), {
      target: { value: 'strobe' },
    });
    await act(async () => {
      fireEvent.submit(screen.getByRole('button', { name: 'Search' }));
    });

    fireEvent.click(screen.getByText('Strobe'));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Submit Request' }));
    });

    expect(screen.getByText('Vote Added!')).toBeInTheDocument();
    expect(screen.getByText('3 people want this song!')).toBeInTheDocument();
  });

  it('auto-closes after 2.5s on success', async () => {
    vi.mocked(api.eventSearch).mockResolvedValue(mockResults);
    vi.mocked(api.submitRequest).mockResolvedValue({
      id: 1,
      artist: 'deadmau5',
      song_title: 'Strobe',
      status: 'new',
      is_duplicate: false,
      vote_count: 0,
    } as never);

    renderModal();

    fireEvent.change(screen.getByPlaceholderText('Search for a song...'), {
      target: { value: 'strobe' },
    });
    await act(async () => {
      fireEvent.submit(screen.getByRole('button', { name: 'Search' }));
    });

    fireEvent.click(screen.getByText('Strobe'));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Submit Request' }));
    });

    expect(mockOnClose).not.toHaveBeenCalled();

    // Advance past 2.5s auto-close
    act(() => {
      vi.advanceTimersByTime(2500);
    });

    expect(mockOnClose).toHaveBeenCalledOnce();
  });

  it('calls onRequestsClosed on 403 error', async () => {
    vi.mocked(api.eventSearch).mockResolvedValue(mockResults);
    vi.mocked(api.submitRequest).mockRejectedValue(
      new (ApiError as unknown as new (msg: string, status: number) => Error)('Requests closed', 403)
    );

    renderModal();

    fireEvent.change(screen.getByPlaceholderText('Search for a song...'), {
      target: { value: 'strobe' },
    });
    await act(async () => {
      fireEvent.submit(screen.getByRole('button', { name: 'Search' }));
    });

    fireEvent.click(screen.getByText('Strobe'));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Submit Request' }));
    });

    expect(mockOnClose).toHaveBeenCalled();
    expect(mockOnRequestsClosed).toHaveBeenCalled();
  });

  it('closes on inactivity timeout (60s)', () => {
    renderModal();

    act(() => {
      vi.advanceTimersByTime(60000);
    });

    expect(mockOnClose).toHaveBeenCalledOnce();
  });

  it('resets inactivity timer on keydown', () => {
    renderModal();

    // Advance 50s (not yet timed out)
    act(() => {
      vi.advanceTimersByTime(50000);
    });
    expect(mockOnClose).not.toHaveBeenCalled();

    // Activity resets the timer
    act(() => {
      window.dispatchEvent(new Event('keydown'));
    });

    // Advance another 50s from the reset point
    act(() => {
      vi.advanceTimersByTime(50000);
    });
    expect(mockOnClose).not.toHaveBeenCalled();

    // 60s after reset → should close
    act(() => {
      vi.advanceTimersByTime(10000);
    });
    expect(mockOnClose).toHaveBeenCalledOnce();
  });

  it('closes when clicking overlay', () => {
    renderModal();

    // The overlay is the outermost div
    const overlay = screen.getByText('Request a Song').closest('.modal-overlay');
    if (overlay) {
      fireEvent.click(overlay);
    }

    expect(mockOnClose).toHaveBeenCalled();
  });

  describe('kiosk virtual keyboard', () => {
    let getItemSpy: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
      getItemSpy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation((key: string) =>
        key === 'kiosk_session_token' ? 'test-token' : null
      );
    });

    afterEach(() => {
      getItemSpy.mockRestore();
    });

    it('keeps keyboard visible after search so touch-through does not close modal', async () => {
      vi.mocked(api.eventSearch).mockResolvedValue(mockResults);

      const { container } = renderModal();

      // Keyboard auto-shows on kiosk devices
      expect(container.querySelector('.kiosk-keyboard-wrapper')).toBeInTheDocument();

      // Type and submit search via the HTML Search button
      fireEvent.change(screen.getByPlaceholderText('Search for a song...'), {
        target: { value: 'strobe' },
      });
      await act(async () => {
        fireEvent.submit(screen.getByRole('button', { name: 'Search' }));
      });

      // Results appear AND keyboard is still visible
      expect(screen.getByText('Strobe')).toBeInTheDocument();
      expect(container.querySelector('.kiosk-keyboard-wrapper')).toBeInTheDocument();
      expect(mockOnClose).not.toHaveBeenCalled();
    });

    it('shows keyboard for note input after selecting a song', async () => {
      vi.mocked(api.eventSearch).mockResolvedValue(mockResults);

      const { container } = renderModal();

      // Search and select a song
      fireEvent.change(screen.getByPlaceholderText('Search for a song...'), {
        target: { value: 'strobe' },
      });
      await act(async () => {
        fireEvent.submit(screen.getByRole('button', { name: 'Search' }));
      });
      fireEvent.click(screen.getByText('Strobe'));

      // Confirm view shows with keyboard still present for the note input
      expect(screen.getByText('Confirm Request')).toBeInTheDocument();
      expect(screen.getByPlaceholderText('Add a note (optional)')).toBeInTheDocument();
      expect(container.querySelector('.kiosk-keyboard-wrapper')).toBeInTheDocument();
    });

    it('labels keyboard done key "Submit" on confirm view to trigger submission', async () => {
      vi.mocked(api.eventSearch).mockResolvedValue(mockResults);

      renderModal();

      // Search and select a song
      fireEvent.change(screen.getByPlaceholderText('Search for a song...'), {
        target: { value: 'strobe' },
      });
      await act(async () => {
        fireEvent.submit(screen.getByRole('button', { name: 'Search' }));
      });

      // Selecting a song triggers: setSelectedSong → auto-show effect →
      // activeInput='note' → doneLabel='Submit' → KioskKeyboard useEffect
      // Wrap in act to flush the full effect chain.
      await act(async () => {
        fireEvent.click(screen.getByText('Strobe'));
      });

      // The keyboard unmounts then remounts when transitioning to confirm view,
      // creating a new instance. Check the latest one.
      const kb = mockKeyboardInstances[mockKeyboardInstances.length - 1];
      expect(kb).toBeDefined();
      const setOptionsCalls = kb.setOptions.mock.calls as Array<[Record<string, Record<string, string>>]>;
      const lastDisplayCall = setOptionsCalls
        .filter((call) => call[0]?.display)
        .pop();
      expect(lastDisplayCall).toBeDefined();
      expect(lastDisplayCall![0].display['{done}']).toBe('Submit');
    });
  });

  it('renders placeholder icon for results without album art', async () => {
    vi.mocked(api.eventSearch).mockResolvedValue([
      {
        title: 'No Art Song', artist: 'Unknown', spotify_id: 'sp3', url: null, album_art: null,
        album: null, popularity: 0, preview_url: null, source: 'spotify' as const,
        genre: null, bpm: null, key: null, isrc: null,
      },
    ]);

    renderModal();

    fireEvent.change(screen.getByPlaceholderText('Search for a song...'), {
      target: { value: 'no art' },
    });
    await act(async () => {
      fireEvent.submit(screen.getByRole('button', { name: 'Search' }));
    });

    expect(screen.getByText('No Art Song')).toBeInTheDocument();
    // Should render SVG placeholder instead of img
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });
});
