/**
 * ImportModal component tests (issue #388) — covers all five import flows:
 * event picker, Tidal/Beatport playlist, public URL validate+import, manual search.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen, waitFor, fireEvent } from '@testing-library/react';
import type { BuilderPlaylists, PoolImportResult, SearchResult } from '@/lib/api-types';
import ImportModal from '../ImportModal';
import type { BuilderCommit } from '../useSetDocumentHistory';

const mockApi = vi.hoisted(() => ({
  getEvents: vi.fn(),
  getBuilderPlaylists: vi.fn(),
  importPoolEvent: vi.fn(),
  importPoolTidal: vi.fn(),
  importPoolBeatport: vi.fn(),
  previewPoolUrl: vi.fn(),
  importPoolUrl: vi.fn(),
  importPoolManual: vi.fn(),
  search: vi.fn(),
}));

vi.mock('@/lib/api', () => ({ api: mockApi }));

const IMPORT_RESULT: PoolImportResult = {
  added: 2,
  deduped: 1,
  source: {
    id: 1,
    kind: 'event',
    external_ref: '7',
    label: 'Prom Night',
    meta: null,
    created_at: '2026-06-09T00:00:00Z',
  },
  pool: { sources: [], tracks: [] },
} as unknown as PoolImportResult;

function importResult(eventId: number, added: number, deduped: number): PoolImportResult {
  return {
    added,
    deduped,
    source: {
      id: eventId,
      kind: 'event',
      external_ref: String(eventId),
      label: `Event ${eventId}`,
      meta: null,
      created_at: '2026-06-09T00:00:00Z',
    },
    pool: {
      sources: [
        {
          id: eventId,
          kind: 'event',
          external_ref: String(eventId),
          label: `Event ${eventId}`,
          meta: null,
          created_at: '2026-06-09T00:00:00Z',
        },
      ],
      tracks: [],
    },
  } as unknown as PoolImportResult;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const PLAYLISTS: BuilderPlaylists = {
  tidal_connected: true,
  beatport_connected: false,
  tidal: [
    {
      id: 'pl-1',
      name: 'Friday Warmup',
      num_tracks: 12,
      source: 'tidal',
      cover_url: null,
      description: null,
    },
  ],
  beatport: [],
};

function makeSearchResult(over: Partial<SearchResult>): SearchResult {
  return {
    title: 'Track',
    artist: 'Artist',
    album: null,
    album_art: null,
    bpm: null,
    genre: null,
    isrc: null,
    key: null,
    popularity: 0,
    preview_url: null,
    source: 'spotify',
    spotify_id: null,
    url: null,
    ...over,
  };
}

const baseProps = {
  setId: 1,
  existingRefs: new Set<string>(),
  onClose: vi.fn(),
  onImported: vi.fn(),
  onError: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ImportModal — event flow', () => {
  it('shows loading then empty state when no events exist', async () => {
    mockApi.getEvents.mockResolvedValue([]);
    render(<ImportModal kind="event" {...baseProps} />);
    expect(screen.getByText('Loading events…')).toBeTruthy();
    expect(await screen.findByText('No events yet.')).toBeTruthy();
  });

  it('treats getEvents failure as an empty list', async () => {
    mockApi.getEvents.mockRejectedValue(new Error('boom'));
    render(<ImportModal kind="event" {...baseProps} />);
    expect(await screen.findByText('No events yet.')).toBeTruthy();
  });

  it('renders owned events as checkboxes, marks imported ones, and keeps import disabled until selection', async () => {
    mockApi.getEvents.mockResolvedValue([
      { id: 7, code: 'ABC123', name: 'Prom Night' },
      { id: 8, code: 'DEF456', name: 'Warehouse' },
    ]);
    mockApi.importPoolEvent.mockResolvedValue(IMPORT_RESULT);
    render(
      <ImportModal
        kind="event"
        {...baseProps}
        existingRefs={new Set(['event:7'])}
      />
    );
    expect(await screen.findByLabelText('Select Prom Night')).toHaveAttribute('type', 'checkbox');
    expect(screen.getByLabelText('Select Warehouse')).toHaveAttribute('type', 'checkbox');
    expect(screen.getByText('· already imported')).toBeTruthy();
    const importBtn = screen.getByText('Import requests') as HTMLButtonElement;
    expect(importBtn.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText('Select Prom Night'));
    expect(importBtn.disabled).toBe(false);
  });

  it('imports selected events sequentially and reports aggregate added/deduped totals', async () => {
    const first = deferred<PoolImportResult>();
    const second = importResult(8, 3, 2);
    mockApi.getEvents.mockResolvedValue([
      { id: 7, code: 'ABC123', name: 'Prom Night' },
      { id: 8, code: 'DEF456', name: 'Warehouse' },
    ]);
    mockApi.importPoolEvent.mockImplementation((_setId: number, eventId: number) =>
      eventId === 7 ? first.promise : Promise.resolve(second),
    );
    const onImported = vi.fn();
    render(<ImportModal kind="event" {...baseProps} onImported={onImported} />);

    fireEvent.click(await screen.findByLabelText('Select Prom Night'));
    fireEvent.click(screen.getByLabelText('Select Warehouse'));
    fireEvent.click(screen.getByText('Import requests'));

    await waitFor(() => expect(mockApi.importPoolEvent).toHaveBeenCalledWith(1, 7));
    expect(mockApi.importPoolEvent).not.toHaveBeenCalledWith(1, 8);

    await act(async () => {
      first.resolve(importResult(7, 2, 1));
      await first.promise;
    });

    await waitFor(() => expect(mockApi.importPoolEvent).toHaveBeenCalledWith(1, 8));
    await waitFor(() =>
      expect(onImported).toHaveBeenCalledWith(
        expect.objectContaining({
          added: 5,
          deduped: 3,
          pool: second.pool,
          source: second.source,
        }),
      ),
    );
  });

  it('allows already-imported events to be selected again for new requests', async () => {
    mockApi.getEvents.mockResolvedValue([{ id: 7, code: 'ABC123', name: 'Prom Night' }]);
    mockApi.importPoolEvent.mockResolvedValue(IMPORT_RESULT);
    render(<ImportModal kind="event" {...baseProps} existingRefs={new Set(['event:7'])} />);

    const checkbox = await screen.findByLabelText('Select Prom Night');
    expect(checkbox).not.toBeDisabled();
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByText('Import requests'));

    await waitFor(() => expect(mockApi.importPoolEvent).toHaveBeenCalledWith(1, 7));
  });

  it('surfaces import errors via onError with the Error message', async () => {
    mockApi.getEvents.mockResolvedValue([{ id: 7, code: 'ABC123', name: 'Prom Night' }]);
    mockApi.importPoolEvent.mockRejectedValue(new Error('Event not found'));
    const onError = vi.fn();
    render(<ImportModal kind="event" {...baseProps} onError={onError} />);
    fireEvent.click(await screen.findByLabelText('Select Prom Night'));
    fireEvent.click(screen.getByText('Import requests'));
    await waitFor(() => expect(onError).toHaveBeenCalledWith('Event not found'));
  });

  it('runs the import mutation inside the document-history commit boundary', async () => {
    mockApi.getEvents.mockResolvedValue([{ id: 7, code: 'ABC123', name: 'Prom Night' }]);
    mockApi.importPoolEvent.mockResolvedValue(IMPORT_RESULT);
    const commitSpy = vi.fn();
    const commit: BuilderCommit = async (label, action) => {
      commitSpy(label, action);
      return action();
    };
    const onImported = vi.fn();
    render(<ImportModal kind="event" {...baseProps} commit={commit} onImported={onImported} />);

    fireEvent.click(await screen.findByLabelText('Select Prom Night'));
    fireEvent.click(screen.getByText('Import requests'));

    await waitFor(() =>
      expect(commitSpy).toHaveBeenCalledWith('Import event requests', expect.any(Function)),
    );
    expect(mockApi.importPoolEvent).toHaveBeenCalledWith(1, 7);
    expect(onImported).toHaveBeenCalledWith(IMPORT_RESULT);
  });

  it('closes via the Cancel button and the backdrop', async () => {
    mockApi.getEvents.mockResolvedValue([]);
    const onClose = vi.fn();
    const { container } = render(<ImportModal kind="event" {...baseProps} onClose={onClose} />);
    await screen.findByText('No events yet.');
    fireEvent.click(screen.getByText('Cancel'));
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(container.querySelector('[class*="modalBackdrop"]')!);
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});

describe('ImportModal — playlist flows', () => {
  it('lists Tidal playlists, marks imported ones, and imports the pick', async () => {
    mockApi.getBuilderPlaylists.mockResolvedValue(PLAYLISTS);
    mockApi.importPoolTidal.mockResolvedValue(IMPORT_RESULT);
    const onImported = vi.fn();
    render(
      <ImportModal
        kind="tidal"
        {...baseProps}
        onImported={onImported}
        existingRefs={new Set(['tidal:pl-1'])}
      />
    );
    expect(screen.getByText('Loading playlists…')).toBeTruthy();
    expect(await screen.findByText('Import Tidal playlist')).toBeTruthy();
    expect(screen.getByText('· already imported')).toBeTruthy();
    expect(screen.getByText('12 tracks')).toBeTruthy();
    fireEvent.click(screen.getByText('Friday Warmup'));
    fireEvent.click(screen.getByText('Import playlist'));
    await waitFor(() =>
      expect(mockApi.importPoolTidal).toHaveBeenCalledWith(1, 'pl-1', 'Friday Warmup')
    );
    expect(onImported).toHaveBeenCalledWith(IMPORT_RESULT);
  });

  it('shows the not-connected notice for Beatport', async () => {
    mockApi.getBuilderPlaylists.mockResolvedValue(PLAYLISTS);
    render(<ImportModal kind="beatport" {...baseProps} />);
    expect(await screen.findByText(/Beatport isn't connected/)).toBeTruthy();
  });

  it('routes Beatport picks through importPoolBeatport and reports generic errors', async () => {
    mockApi.getBuilderPlaylists.mockResolvedValue({
      ...PLAYLISTS,
      beatport_connected: true,
      beatport: [
        {
          id: 'bp-9',
          name: 'Peak Time',
          num_tracks: 30,
          source: 'beatport',
          cover_url: null,
          description: null,
        },
      ],
    });
    mockApi.importPoolBeatport.mockRejectedValue('not-an-error');
    const onError = vi.fn();
    render(<ImportModal kind="beatport" {...baseProps} onError={onError} />);
    fireEvent.click(await screen.findByText('Peak Time'));
    fireEvent.click(screen.getByText('Import playlist'));
    await waitFor(() =>
      expect(mockApi.importPoolBeatport).toHaveBeenCalledWith(1, 'bp-9', 'Peak Time')
    );
    expect(onError).toHaveBeenCalledWith('Import failed — try again');
  });
});

describe('ImportModal — public URL flow', () => {
  it('enables Validate only for https URLs and imports a supported preview', async () => {
    mockApi.previewPoolUrl.mockResolvedValue({
      supported: true,
      provider: 'spotify',
      name: 'Summer Mix',
      track_count: 42,
      owner: 'DJ Wrz',
      message: null,
    });
    mockApi.importPoolUrl.mockResolvedValue(IMPORT_RESULT);
    const onImported = vi.fn();
    render(<ImportModal kind="public_url" {...baseProps} onImported={onImported} />);
    const input = screen.getByPlaceholderText('https://open.spotify.com/playlist/…');
    const validateBtn = screen.getByText('Validate') as HTMLButtonElement;
    expect(validateBtn.disabled).toBe(true);
    fireEvent.change(input, { target: { value: 'http://not-secure.com/x' } });
    expect(validateBtn.disabled).toBe(true);
    fireEvent.change(input, { target: { value: ' https://open.spotify.com/playlist/abc ' } });
    expect(validateBtn.disabled).toBe(false);
    fireEvent.click(validateBtn);
    await waitFor(() =>
      expect(mockApi.previewPoolUrl).toHaveBeenCalledWith(1, 'https://open.spotify.com/playlist/abc')
    );
    expect(await screen.findByText('Spotify · public playlist')).toBeTruthy();
    expect(screen.getByText('Summer Mix')).toBeTruthy();
    expect(screen.getByText('42 found · de-duped on import')).toBeTruthy();
    expect(screen.getByText('DJ Wrz')).toBeTruthy();
    fireEvent.click(screen.getByText('Import playlist'));
    await waitFor(() =>
      expect(mockApi.importPoolUrl).toHaveBeenCalledWith(1, 'https://open.spotify.com/playlist/abc')
    );
    expect(onImported).toHaveBeenCalledWith(IMPORT_RESULT);
  });

  it('renders Tidal previews with em-dash fallbacks for missing fields', async () => {
    mockApi.previewPoolUrl.mockResolvedValue({
      supported: true,
      provider: 'tidal',
      name: null,
      track_count: null,
      owner: null,
      message: null,
    });
    render(<ImportModal kind="public_url" {...baseProps} />);
    fireEvent.change(screen.getByPlaceholderText('https://open.spotify.com/playlist/…'), {
      target: { value: 'https://tidal.com/playlist/xyz' },
    });
    fireEvent.click(screen.getByText('Validate'));
    expect(await screen.findByText('Tidal · public playlist')).toBeTruthy();
    expect(screen.getByText('—')).toBeTruthy();
    expect(screen.getByText('— found · de-duped on import')).toBeTruthy();
    // owner row hidden when owner is null
    expect(screen.queryByText('Owner')).toBeNull();
  });

  it('shows unsupported-provider message (and a fallback when message is null)', async () => {
    mockApi.previewPoolUrl.mockResolvedValueOnce({
      supported: false,
      provider: 'unknown',
      name: null,
      track_count: null,
      owner: null,
      message: 'Apple Music is not supported yet',
    });
    render(<ImportModal kind="public_url" {...baseProps} />);
    const input = screen.getByPlaceholderText('https://open.spotify.com/playlist/…');
    fireEvent.change(input, { target: { value: 'https://music.apple.com/playlist/1' } });
    fireEvent.click(screen.getByText('Validate'));
    expect(await screen.findByText('Apple Music is not supported yet')).toBeTruthy();
    const importBtn = screen.getByText('Import playlist') as HTMLButtonElement;
    expect(importBtn.disabled).toBe(true);

    mockApi.previewPoolUrl.mockResolvedValueOnce({
      supported: false,
      provider: 'unknown',
      name: null,
      track_count: null,
      owner: null,
      message: null,
    });
    fireEvent.change(input, { target: { value: 'https://example.com/other' } });
    fireEvent.click(screen.getByText('Validate'));
    expect(await screen.findByText('Provider not supported yet.')).toBeTruthy();
  });

  it('shows validation errors and clears them when the URL changes', async () => {
    mockApi.previewPoolUrl.mockRejectedValue(new Error('URL host not allowed'));
    render(<ImportModal kind="public_url" {...baseProps} />);
    const input = screen.getByPlaceholderText('https://open.spotify.com/playlist/…');
    fireEvent.change(input, { target: { value: 'https://evil.example/playlist' } });
    fireEvent.click(screen.getByText('Validate'));
    expect(await screen.findByText('URL host not allowed')).toBeTruthy();
    fireEvent.change(input, { target: { value: 'https://evil.example/playlist2' } });
    expect(screen.queryByText('URL host not allowed')).toBeNull();
  });

  it('reports import failures via onError', async () => {
    mockApi.previewPoolUrl.mockResolvedValue({
      supported: true,
      provider: 'spotify',
      name: 'Mix',
      track_count: 1,
      owner: null,
      message: null,
    });
    mockApi.importPoolUrl.mockRejectedValue(new Error('Playlist gone'));
    const onError = vi.fn();
    render(<ImportModal kind="public_url" {...baseProps} onError={onError} />);
    fireEvent.change(screen.getByPlaceholderText('https://open.spotify.com/playlist/…'), {
      target: { value: 'https://open.spotify.com/playlist/abc' },
    });
    fireEvent.click(screen.getByText('Validate'));
    await screen.findByText('Spotify · public playlist');
    fireEvent.click(screen.getByText('Import playlist'));
    await waitFor(() => expect(onError).toHaveBeenCalledWith('Playlist gone'));
  });
});

describe('ImportModal — manual search flow', () => {
  it('prompts to type, then searches after debounce and renders BPM/key metadata', async () => {
    mockApi.search.mockResolvedValue([
      makeSearchResult({
        title: 'With Meta',
        artist: 'A1',
        bpm: 128,
        key: '8A',
        source: 'beatport',
        url: 'https://beatport.com/track/1',
      }),
      makeSearchResult({ title: 'Bare', artist: 'A2', source: 'tidal', url: 'https://t/2' }),
    ]);
    render(<ImportModal kind="manual" {...baseProps} />);
    expect(screen.getByText('Type to search Spotify, Beatport, Tidal…')).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText('Search title or artist…'), {
      target: { value: 'meta' },
    });
    await waitFor(() => expect(mockApi.search).toHaveBeenCalledWith('meta'));
    expect(await screen.findByText('With Meta')).toBeTruthy();
    expect(screen.getByText(/A1 · 128 BPM · 8A · beatport/)).toBeTruthy();
    expect(screen.getByText(/A2 · tidal/)).toBeTruthy();
  });

  it('imports a Spotify pick with its spotify_id and https artwork', async () => {
    mockApi.search.mockResolvedValue([
      makeSearchResult({
        title: 'Sp Track',
        artist: 'Sp Artist',
        album: 'Sp Album',
        genre: 'House',
        bpm: 124,
        key: 'Am',
        isrc: 'US123',
        album_art: 'https://img.example/a.jpg',
        source: 'spotify',
        spotify_id: 'sp-1',
      }),
    ]);
    mockApi.importPoolManual.mockResolvedValue(IMPORT_RESULT);
    const onImported = vi.fn();
    render(<ImportModal kind="manual" {...baseProps} onImported={onImported} />);
    fireEvent.change(screen.getByPlaceholderText('Search title or artist…'), {
      target: { value: 'sp' },
    });
    fireEvent.click(await screen.findByText('Sp Track'));
    await waitFor(() =>
      expect(mockApi.importPoolManual).toHaveBeenCalledWith(1, {
        title: 'Sp Track',
        artist: 'Sp Artist',
        album: 'Sp Album',
        genre: 'House',
        bpm: 124,
        key: 'Am',
        isrc: 'US123',
        artwork_url: 'https://img.example/a.jpg',
        source_service: 'spotify',
        source_track_id: 'sp-1',
      })
    );
    expect(onImported).toHaveBeenCalledWith(IMPORT_RESULT);
  });

  it('falls back to manual source and drops non-https artwork for unknown sources', async () => {
    mockApi.search.mockResolvedValue([
      makeSearchResult({
        title: 'Odd Track',
        artist: 'Odd Artist',
        album_art: 'http://insecure.example/a.jpg',
        source: 'soundcloud',
      }),
    ]);
    mockApi.importPoolManual.mockRejectedValue(new Error('Pool is full'));
    const onError = vi.fn();
    render(<ImportModal kind="manual" {...baseProps} onError={onError} />);
    fireEvent.change(screen.getByPlaceholderText('Search title or artist…'), {
      target: { value: 'odd' },
    });
    fireEvent.click(await screen.findByText('Odd Track'));
    await waitFor(() =>
      expect(mockApi.importPoolManual).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          artwork_url: null,
          source_service: 'manual',
          source_track_id: null,
        })
      )
    );
    expect(onError).toHaveBeenCalledWith('Pool is full');
  });

  it('shows "No matches." when a search returns nothing (or fails)', async () => {
    mockApi.search.mockRejectedValue(new Error('rate limited'));
    render(<ImportModal kind="manual" {...baseProps} />);
    fireEvent.change(screen.getByPlaceholderText('Search title or artist…'), {
      target: { value: 'zz' },
    });
    await waitFor(() => expect(mockApi.search).toHaveBeenCalled());
    expect(await screen.findByText('No matches.')).toBeTruthy();
    // clearing back below 2 chars returns to the type-to-search prompt
    fireEvent.change(screen.getByPlaceholderText('Search title or artist…'), {
      target: { value: 'z' },
    });
    expect(screen.getByText('Type to search Spotify, Beatport, Tidal…')).toBeTruthy();
  });
});
