/**
 * ExportModal component tests (issue #396) — setlist export.
 * Covers: platform picker, preflight check, resolution interrupt,
 * Tidal export, file downloads, M3U/txt dual-button, pool notice.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import type { ExportPreflight, ExportTidalResult, SetDetail } from '@/lib/api-types';
import ExportModal from '../ExportModal';

// ---- Mock the API singleton ----

const mockApi = vi.hoisted(() => ({
  exportPreflight: vi.fn(),
  exportSetToTidal: vi.fn(),
  exportSetFile: vi.fn(),
}));

vi.mock('@/lib/api', () => ({ api: mockApi }));

// ---- DOM helpers for download ----
// We stub URL.createObjectURL / revokeObjectURL + HTMLAnchorElement.prototype.click
// so triggerDownload doesn't crash in jsdom with navigation warnings.

const createObjectURLSpy = vi.fn(() => 'blob:mock-url');
const revokeObjectURLSpy = vi.fn();
Object.defineProperty(URL, 'createObjectURL', { value: createObjectURLSpy, writable: true });
Object.defineProperty(URL, 'revokeObjectURL', { value: revokeObjectURLSpy, writable: true });
HTMLAnchorElement.prototype.click = vi.fn();

// ---- Fixtures ----

function makeSet(overrides: Partial<SetDetail> = {}): SetDetail {
  return {
    id: 42,
    name: 'Friday Wedding',
    event_id: null,
    status: 'draft',
    sharing_mode: 'private',
    share_token: null,
    vibe_theme: null,
    target_duration_sec: null,
    avg_transition_overlap_sec: 8,
    bpm_floor: null,
    bpm_ceiling: null,
    key_strictness: 0,
    tidal_playlist_id: null,
    exported_at: null,
    created_at: '2026-06-10T00:00:00Z',
    updated_at: '2026-06-10T00:00:00Z',
    ...overrides,
  };
}

function makePreflightClean(target: ExportPreflight['target'] = 'rekordbox'): ExportPreflight {
  return {
    target,
    source: 'timeline',
    total: 10,
    resolved_count: 10,
    unresolved: [],
    tidal_connected: null,
  };
}

function makePreflightWithUnresolved(
  target: ExportPreflight['target'] = 'rekordbox'
): ExportPreflight {
  // Backend sets reason per target: tidal preflight → no_tidal_match,
  // file targets (rekordbox/m3u/txt) → missing_metadata.
  const reason = target === 'tidal' ? ('no_tidal_match' as const) : ('missing_metadata' as const);
  return {
    target,
    source: 'timeline',
    total: 12,
    resolved_count: 10,
    unresolved: [
      {
        position: 3,
        title: 'Ghost Track',
        artist: 'Unknown',
        track_id: 'bp-99',
        reason,
      },
      {
        position: 7,
        title: '',
        artist: '',
        track_id: 'bp-404',
        reason,
      },
    ],
    tidal_connected: null,
  };
}

const TIDAL_RESULT: ExportTidalResult = {
  playlist_id: 'pl-1',
  playlist_url: 'https://tidal.com/playlist/pl-1',
  added: 10,
  skipped: 0,
  exported_at: '2026-06-10T12:00:00Z',
  status: 'exported',
};

const baseProps = {
  set: makeSet(),
  onClose: vi.fn(),
  onSetUpdated: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
  createObjectURLSpy.mockReturnValue('blob:mock-url');
});

// ============================================================
// 1. Platform picker — all 8 rows, 3 disabled with "Coming soon"
// ============================================================

describe('ExportModal — platform picker', () => {
  it('renders all 8 platform rows with 3 disabled and showing "Coming soon"', () => {
    render(<ExportModal {...baseProps} />);

    // Available platforms (Engine DJ + Lexicon both ship via Rekordbox XML)
    expect(screen.getByText('Tidal')).toBeTruthy();
    expect(screen.getByText('Rekordbox XML')).toBeTruthy();
    expect(screen.getByText('M3U / .txt')).toBeTruthy();
    expect(screen.getByText('Engine DJ XML')).toBeTruthy();
    expect(screen.getByText('Lexicon')).toBeTruthy();

    // Unavailable platforms
    expect(screen.getByText('Serato .crate')).toBeTruthy();
    expect(screen.getByText('Spotify')).toBeTruthy();
    expect(screen.getByText('Apple Music')).toBeTruthy();

    // Exactly 3 "Coming soon" badges
    const comingSoonBadges = screen.getAllByText('Coming soon');
    expect(comingSoonBadges).toHaveLength(3);
  });

  it('Engine DJ and Lexicon rows are enabled (not "Coming soon")', () => {
    render(<ExportModal {...baseProps} />);
    const engineBtn = screen.getByRole('button', { name: /engine dj xml/i });
    const lexiconBtn = screen.getByRole('button', { name: /lexicon/i });
    expect((engineBtn as HTMLButtonElement).disabled).toBe(false);
    expect((lexiconBtn as HTMLButtonElement).disabled).toBe(false);
  });

  it('unavailable rows are disabled and clicking them does not call exportPreflight', () => {
    render(<ExportModal {...baseProps} />);

    // Find the Spotify button (unavailable row)
    const spotifyBtn = screen.getByRole('button', { name: /spotify/i });
    expect((spotifyBtn as HTMLButtonElement).disabled).toBe(true);

    // Clicking a disabled button must not trigger the preflight call
    fireEvent.click(spotifyBtn);
    expect(mockApi.exportPreflight).not.toHaveBeenCalled();
  });
});

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

  it('shows the import-then-relink note for these targets', async () => {
    mockApi.exportPreflight.mockResolvedValue(makePreflightClean('enginedj'));
    render(<ExportModal {...baseProps} />);
    fireEvent.click(screen.getByText('Engine DJ XML'));
    await waitFor(() => {
      expect(screen.getByText(/relink/i)).toBeTruthy();
    });
  });
});
