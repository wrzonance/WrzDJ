import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SPOTIFY_RESULT, TIDAL_RESULT, baseProps, createObjectURLSpy, getMockApi, makePreflightClean, makePreflightWithUnresolved, revokeObjectURLSpy } from './ExportModalTestSupport';
import ExportModal from '../ExportModal';

const mockApi = getMockApi();
import type { ExportPreflight } from '@/lib/api/types';



// ============================================================
// 2. Rekordbox: preflight with no unresolved → Download .xml appears
// ============================================================

describe('ExportModal — Rekordbox clean preflight', () => {
  it('calls exportPreflight(set.id, "rekordbox") then shows Download .xml', async () => {
    mockApi.exportPreflight.mockResolvedValue(makePreflightClean('rekordbox'));

    render(<ExportModal {...baseProps} />);

    // Click the Rekordbox row
    fireEvent.click(screen.getByText('Rekordbox XML'));

    // During preflight we show "Checking…" or "Loading" message of some kind
    // (we don't assert exact copy to be brittle-resistant)
    await waitFor(() => {
      expect(mockApi.exportPreflight).toHaveBeenCalledWith(42, 'rekordbox');
    });

    // With zero unresolved, download button should appear immediately
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /download.*xml/i })).toBeTruthy();
    });
  });
});


// ============================================================
// 3. Resolution interrupt: unresolved tracks shown, export gate,
//    Cancel returns to picker
// ============================================================

describe('ExportModal — resolution interrupt', () => {
  it('shows unresolved list with titles and reasons; no export button until skip is clicked', async () => {
    mockApi.exportPreflight.mockResolvedValue(makePreflightWithUnresolved('rekordbox'));

    render(<ExportModal {...baseProps} />);
    fireEvent.click(screen.getByText('Rekordbox XML'));

    await waitFor(() => {
      expect(mockApi.exportPreflight).toHaveBeenCalledWith(42, 'rekordbox');
    });

    // Unresolved tracks are listed
    await waitFor(() => {
      expect(screen.getByText(/Ghost Track/)).toBeTruthy();
    });

    // When title is empty, falls back to track_id
    expect(screen.getByText(/bp-404/)).toBeTruthy();

    // Reason strings rendered (file targets always report missing_metadata)
    expect(screen.getAllByText(/missing_metadata/)).toHaveLength(2);

    // No download/export button until skipped
    expect(screen.queryByRole('button', { name: /download.*xml/i })).toBeNull();

    // The skip button exists
    expect(screen.getByRole('button', { name: /skip.*continue/i })).toBeTruthy();
  });

  it('Cancel on interrupt returns to platform picker without calling exportSetFile', async () => {
    mockApi.exportPreflight.mockResolvedValue(makePreflightWithUnresolved('rekordbox'));

    render(<ExportModal {...baseProps} />);
    fireEvent.click(screen.getByText('Rekordbox XML'));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /skip.*continue/i })).toBeTruthy();
    });

    // Click Cancel
    fireEvent.click(screen.getByRole('button', { name: /^cancel$/i }));

    // Platform list is visible again
    await waitFor(() => {
      expect(screen.getByText('Rekordbox XML')).toBeTruthy();
      expect(screen.getByText('Tidal')).toBeTruthy();
    });

    // No export was called
    expect(mockApi.exportSetFile).not.toHaveBeenCalled();
  });
});


// ============================================================
// 4. After skipping, Download .xml calls exportSetFile correctly
// ============================================================

describe('ExportModal — file download after skip', () => {
  it('calls exportSetFile(42, "rekordbox", true, ...) and triggers download', async () => {
    mockApi.exportPreflight.mockResolvedValue(makePreflightWithUnresolved('rekordbox'));
    const mockBlob = new Blob(['<xml/>'], { type: 'application/xml' });
    mockApi.exportSetFile.mockResolvedValue({ blob: mockBlob, filename: 'set.xml' });

    render(<ExportModal {...baseProps} />);
    fireEvent.click(screen.getByText('Rekordbox XML'));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /skip.*continue/i })).toBeTruthy();
    });

    // Click skip
    fireEvent.click(screen.getByRole('button', { name: /skip.*continue/i }));

    // Download button should now appear
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /download.*xml/i })).toBeTruthy();
    });

    // Click it
    fireEvent.click(screen.getByRole('button', { name: /download.*xml/i }));

    await waitFor(() => {
      expect(mockApi.exportSetFile).toHaveBeenCalledWith(42, 'rekordbox', true, expect.any(String));
    });

    // createObjectURL was called (download triggered) and revokeObjectURL cleans up
    expect(createObjectURLSpy).toHaveBeenCalled();
    await waitFor(() => {
      expect(revokeObjectURLSpy).toHaveBeenCalledWith('blob:mock-url');
    });
  });
});


// ============================================================
// 5. Tidal: not connected → guidance + no export button;
//    connected + no unresolved → export → success panel + onSetUpdated
// ============================================================

describe('ExportModal — Tidal export', () => {
  it('shows connect-tidal guidance and no export button when tidal_connected=false', async () => {
    mockApi.exportPreflight.mockResolvedValue({
      ...makePreflightClean('tidal'),
      tidal_connected: false,
    });

    render(<ExportModal {...baseProps} />);
    fireEvent.click(screen.getByText('Tidal'));

    await waitFor(() => {
      expect(mockApi.exportPreflight).toHaveBeenCalledWith(42, 'tidal');
    });

    await waitFor(() => {
      // Some guidance text mentioning Connect Tidal
      expect(screen.getByText(/connect tidal/i)).toBeTruthy();
    });

    // No export button
    expect(screen.queryByRole('button', { name: /export to tidal/i })).toBeNull();
  });

  it('tidal_connected=true, no unresolved → export button → success panel + onSetUpdated', async () => {
    mockApi.exportPreflight.mockResolvedValue({
      ...makePreflightClean('tidal'),
      tidal_connected: true,
    });
    mockApi.exportSetToTidal.mockResolvedValue(TIDAL_RESULT);
    const onSetUpdated = vi.fn();

    render(<ExportModal {...baseProps} onSetUpdated={onSetUpdated} />);
    fireEvent.click(screen.getByText('Tidal'));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /export to tidal/i })).toBeTruthy();
    });

    fireEvent.click(screen.getByRole('button', { name: /export to tidal/i }));

    await waitFor(() => {
      expect(mockApi.exportSetToTidal).toHaveBeenCalledWith(42, false);
    });

    // Success panel: playlist link appears
    await waitFor(() => {
      const link = screen.getByRole('link', { name: /open in tidal/i }) as HTMLAnchorElement;
      expect(link.href).toContain('tidal.com/playlist/pl-1');
    });

    // onSetUpdated called with the right patch
    expect(onSetUpdated).toHaveBeenCalledWith({
      status: 'exported',
      tidal_playlist_id: 'pl-1',
      exported_at: '2026-06-10T12:00:00Z',
    });
  });
});


describe('ExportModal — Spotify export', () => {
  it('shows a connect action and blocks export when Spotify is not linked', async () => {
    mockApi.exportPreflight.mockResolvedValue({
      ...makePreflightClean('spotify'),
      spotify_connected: false,
    });
    mockApi.startSpotifyAuthorization.mockResolvedValue({
      authorization_url: 'https://accounts.spotify.com/authorize?state=state',
    });

    render(<ExportModal {...baseProps} />);
    fireEvent.click(screen.getByText('Spotify'));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /connect spotify/i })).toBeTruthy();
    });
    expect(screen.queryByRole('button', { name: /export to spotify/i })).toBeNull();
  });

  it('exports after connected preflight and shows Spotify playlist result', async () => {
    mockApi.exportPreflight.mockResolvedValue({
      ...makePreflightClean('spotify'),
      spotify_connected: true,
    });
    mockApi.exportSetToSpotify.mockResolvedValue(SPOTIFY_RESULT);
    const onSetUpdated = vi.fn();

    render(<ExportModal {...baseProps} onSetUpdated={onSetUpdated} />);
    fireEvent.click(screen.getByText('Spotify'));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /export to spotify/i })).toBeTruthy();
    });
    fireEvent.click(screen.getByRole('button', { name: /export to spotify/i }));

    await waitFor(() => {
      expect(mockApi.exportSetToSpotify).toHaveBeenCalledWith(42, false);
      expect(screen.getByRole('link', { name: /open in spotify/i })).toBeTruthy();
    });
    expect(onSetUpdated).toHaveBeenCalledWith({
      status: 'exported',
      spotify_playlist_id: 'spotify-pl-1',
      exported_at: '2026-06-10T12:00:00Z',
    });
  });
});


// ============================================================
// 6. source='pool' → timeline-empty / pool notice shown
// ============================================================

describe('ExportModal — pool source notice', () => {
  it('shows the pool source notice when preflight source is "pool"', async () => {
    mockApi.exportPreflight.mockResolvedValue({
      ...makePreflightClean('rekordbox'),
      source: 'pool',
    });

    render(<ExportModal {...baseProps} />);
    fireEvent.click(screen.getByText('Rekordbox XML'));

    await waitFor(() => {
      // Should show something mentioning pool or timeline empty
      expect(screen.getByText(/pool/i)).toBeTruthy();
    });
  });
});


// ============================================================
// 7. M3U row: one preflight → two download buttons
// ============================================================

describe('ExportModal — M3U dual-download', () => {
  it('shows both Download .m3u8 and Download .txt after M3U preflight', async () => {
    mockApi.exportPreflight.mockResolvedValue(makePreflightClean('m3u'));
    const mockBlob = new Blob(['#EXTM3U'], { type: 'audio/x-mpegurl' });
    mockApi.exportSetFile.mockResolvedValue({ blob: mockBlob, filename: 'set.m3u8' });

    render(<ExportModal {...baseProps} />);
    fireEvent.click(screen.getByText('M3U / .txt'));

    await waitFor(() => {
      expect(mockApi.exportPreflight).toHaveBeenCalledWith(42, 'm3u');
    });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /download.*m3u8/i })).toBeTruthy();
      expect(screen.getByRole('button', { name: /download.*txt/i })).toBeTruthy();
    });

    // Click m3u8 download → calls format 'm3u'
    fireEvent.click(screen.getByRole('button', { name: /download.*m3u8/i }));
    await waitFor(() => {
      expect(mockApi.exportSetFile).toHaveBeenCalledWith(42, 'm3u', false, expect.any(String));
    });

    vi.clearAllMocks();
    mockApi.exportSetFile.mockResolvedValue({ blob: mockBlob, filename: 'set.txt' });

    // Click txt download → calls format 'txt'
    fireEvent.click(screen.getByRole('button', { name: /download.*txt/i }));
    await waitFor(() => {
      expect(mockApi.exportSetFile).toHaveBeenCalledWith(42, 'txt', false, expect.any(String));
    });
  });
});


// ============================================================
// 8. Engine DJ + Lexicon: preflight → Download .xml via Rekordbox XML
// ============================================================

describe('ExportModal — Engine DJ + Lexicon (Rekordbox XML)', () => {
  it.each([
    ['Engine DJ XML', 'enginedj'],
    ['Lexicon', 'lexicon'],
  ])('%s preflights as %s then downloads .xml', async (label, format) => {
    mockApi.exportPreflight.mockResolvedValue(
      makePreflightClean(format as ExportPreflight['target'])
    );
    const mockBlob = new Blob(['<DJ_PLAYLISTS/>'], { type: 'application/xml' });
    mockApi.exportSetFile.mockResolvedValue({ blob: mockBlob, filename: `set.xml` });

    render(<ExportModal {...baseProps} />);
    fireEvent.click(screen.getByText(label));

    await waitFor(() => {
      expect(mockApi.exportPreflight).toHaveBeenCalledWith(42, format);
    });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /download.*xml/i })).toBeTruthy();
    });

    fireEvent.click(screen.getByRole('button', { name: /download.*xml/i }));
    await waitFor(() => {
      expect(mockApi.exportSetFile).toHaveBeenCalledWith(42, format, false, expect.any(String));
    });
  });

  it.each([
    ['Engine DJ XML', 'enginedj'],
    ['Lexicon', 'lexicon'],
  ])('%s shows the import-then-relink note', async (label, format) => {
    mockApi.exportPreflight.mockResolvedValue(
      makePreflightClean(format as ExportPreflight['target'])
    );
    render(<ExportModal {...baseProps} />);
    fireEvent.click(screen.getByText(label));
    await waitFor(() => {
      expect(screen.getByText(/relink/i)).toBeTruthy();
    });
  });
});
