import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { baseProps, getMockApi, makePreflightClean, makeSet } from './ExportModalTestSupport';
import ExportModal from '../ExportModal';
import { ApiError } from '@/lib/api';

const mockApi = getMockApi();


// ============================================================
// 1. Platform picker — Apple Music export is available
// ============================================================

describe('ExportModal — platform picker', () => {
  it('renders all 8 platform rows with only Serato showing "Coming soon"', () => {
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

    // Only Serato remains unavailable.
    const comingSoonBadges = screen.getAllByText('Coming soon');
    expect(comingSoonBadges).toHaveLength(1);
  });

  it('Engine DJ and Lexicon rows are enabled (not "Coming soon")', () => {
    render(<ExportModal {...baseProps} />);
    const engineBtn = screen.getByRole('button', { name: /engine dj xml/i });
    const lexiconBtn = screen.getByRole('button', { name: /lexicon/i });
    expect((engineBtn as HTMLButtonElement).disabled).toBe(false);
    expect((lexiconBtn as HTMLButtonElement).disabled).toBe(false);
  });

  it('explains when Apple Music is unavailable because deployment credentials are missing', async () => {
    mockApi.exportPreflight.mockRejectedValue(
      new ApiError('Apple Music is not configured', 503),
    );

    render(<ExportModal {...baseProps} />);
    fireEvent.click(screen.getByText('Apple Music'));

    expect(
      await screen.findByText(
        "Apple Music export is unavailable because this deployment is not configured.",
      ),
    ).toBeTruthy();
  });

  it('connects Apple Music, preflights again, then exports the set', async () => {
    mockApi.exportPreflight
      .mockResolvedValueOnce({ ...makePreflightClean('apple_music'), apple_music_connected: false })
      .mockResolvedValueOnce({ ...makePreflightClean('apple_music'), apple_music_connected: true });
    mockApi.getAppleMusicDeveloperToken.mockResolvedValue({
      developer_token: 'developer-token',
      expires_at: 100,
    });
    mockApi.linkAppleMusicAccount.mockResolvedValue({
      configured: true,
      linked: true,
      requires_reauthorization: false,
      storefront: 'gb',
    });
    mockApi.exportSetToAppleMusic.mockResolvedValue({
      playlist_id: 'p.playlist123',
      playlist_url: 'https://music.apple.com/gb/library/playlist/p.playlist123',
      added: 10,
      skipped: 0,
      exported_at: '2026-06-10T12:00:00Z',
      status: 'exported',
    });
    const authorize = vi.fn().mockResolvedValue('music-user-token-secret');
    Object.defineProperty(window, 'MusicKit', {
      configurable: true,
      value: {
        configure: vi.fn().mockResolvedValue(undefined),
        getInstance: () => ({ authorize }),
      },
    });
    const onSetUpdated = vi.fn();

    render(<ExportModal {...baseProps} onSetUpdated={onSetUpdated} />);
    fireEvent.click(screen.getByText('Apple Music'));
    await waitFor(() => expect(screen.getByRole('button', { name: /connect apple music/i })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /connect apple music/i }));

    await waitFor(() => expect(mockApi.linkAppleMusicAccount).toHaveBeenCalledWith('music-user-token-secret'));
    await waitFor(() => expect(screen.getByRole('button', { name: /export to apple music/i })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /export to apple music/i }));

    await waitFor(() => {
      expect(mockApi.exportSetToAppleMusic).toHaveBeenCalledWith(42, false);
      expect(screen.getByRole('link', { name: /open in apple music/i })).toBeTruthy();
    });
    expect(onSetUpdated).toHaveBeenCalledWith({
      status: 'exported',
      apple_music_playlist_id: 'p.playlist123',
      exported_at: '2026-06-10T12:00:00Z',
    });
  });

  it.each([
    ['known playlist ID', 'p.playlist123'],
    ['unknown playlist ID', null],
  ])('prevents retrying an unconfirmed Apple Music export with %s', async (_label, playlistId) => {
    mockApi.exportPreflight.mockResolvedValue(makePreflightClean('apple_music'));
    const onSetUpdated = vi.fn();
    const message = 'Apple Music export could not be confirmed. Do not retry; check your library.';
    const actualApi = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      detail: { code: 'apple_music_write_uncertain', message, playlist_id: playlistId },
    }), { status: 502 })));
    mockApi.exportSetToAppleMusic.mockImplementation((setId, skipUnresolved) =>
      actualApi.api.exportSetToAppleMusic(setId, skipUnresolved),
    );

    render(<ExportModal {...baseProps} onSetUpdated={onSetUpdated} />);
    fireEvent.click(screen.getByText('Apple Music'));
    fireEvent.click(await screen.findByRole('button', { name: /export to apple music/i }));

    expect(await screen.findByText(message)).toBeTruthy();
    if (playlistId) {
      expect(screen.getByText(/p\.playlist123/)).toBeTruthy();
    } else {
      expect(screen.queryByText(/p\.playlist123/)).toBeNull();
    }
    expect(screen.queryByRole('button', { name: /export to apple music/i })).toBeNull();
    expect(screen.getByRole('button', { name: /back/i })).toBeTruthy();
    expect(mockApi.exportSetToAppleMusic).toHaveBeenCalledTimes(1);
    expect(onSetUpdated).toHaveBeenCalledWith({
      apple_music_export_uncertain: true,
      apple_music_export_recovery_playlist_id: playlistId,
    });
  });

  it('recovers a saved ambiguous export when the DJ finds its playlist', async () => {
    mockApi.reconcileAppleMusicExport.mockResolvedValue({ status: 'exported' });
    const onSetUpdated = vi.fn();

    render(
      <ExportModal
        {...baseProps}
        set={makeSet({
          apple_music_export_uncertain: true,
          apple_music_export_recovery_playlist_id: 'p.savedPlaylist',
        })}
        onSetUpdated={onSetUpdated}
      />,
    );

    expect(await screen.findByText(/check your apple music library/i)).toBeTruthy();
    expect(screen.getByRole('textbox', { name: /playlist id/i })).toHaveProperty(
      'value',
      'p.savedPlaylist',
    );
    expect(screen.queryByText('Choose a platform or format')).toBeNull();
    expect(screen.queryByRole('button', { name: /export to apple music/i })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /i found the playlist/i }));

    await waitFor(() => {
      expect(mockApi.reconcileAppleMusicExport).toHaveBeenCalledWith(42, {
        action: 'playlist_found',
        playlist_id: 'p.savedPlaylist',
      });
      expect(onSetUpdated).toHaveBeenCalledWith({
        status: 'exported',
        apple_music_playlist_id: 'p.savedPlaylist',
        apple_music_export_uncertain: false,
        apple_music_export_recovery_playlist_id: null,
      });
      expect(screen.getByText(/playlist confirmed/i)).toBeTruthy();
    });
    expect(mockApi.exportSetToAppleMusic).not.toHaveBeenCalled();
  });

  it('requires a second confirmation before clearing an ambiguous export with no playlist found', async () => {
    mockApi.reconcileAppleMusicExport.mockResolvedValue({ status: 'ready_to_retry' });
    const onSetUpdated = vi.fn();

    render(
      <ExportModal
        {...baseProps}
        set={makeSet({ apple_music_export_uncertain: true })}
        onSetUpdated={onSetUpdated}
      />,
    );

    fireEvent.click(await screen.findByRole('button', { name: /i couldn't find the playlist/i }));
    expect(screen.getByText(/confirm that you checked your library/i)).toBeTruthy();
    expect(mockApi.reconcileAppleMusicExport).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /yes, no playlist was found/i }));

    await waitFor(() => {
      expect(mockApi.reconcileAppleMusicExport).toHaveBeenCalledWith(42, {
        action: 'playlist_absent',
      });
      expect(onSetUpdated).toHaveBeenCalledWith({
        apple_music_export_uncertain: false,
        apple_music_export_recovery_playlist_id: null,
      });
      expect(screen.getByText(/you can start a new export when you.re ready/i)).toBeTruthy();
    });
    expect(mockApi.exportSetToAppleMusic).not.toHaveBeenCalled();
  });

  it('keeps playlist recovery retryable when reconciliation returns a conflicting status', async () => {
    // Baseline 57cfcdc6867f: do not report recovery when the server contradicts the DJ's confirmation.
    mockApi.reconcileAppleMusicExport
      .mockResolvedValueOnce({ status: 'ready_to_retry' })
      .mockResolvedValueOnce({ status: 'exported' });
    const onSetUpdated = vi.fn();

    render(
      <ExportModal
        {...baseProps}
        set={makeSet({
          apple_music_export_uncertain: true,
          apple_music_export_recovery_playlist_id: 'p.savedPlaylist',
        })}
        onSetUpdated={onSetUpdated}
      />,
    );

    fireEvent.click(await screen.findByRole('button', { name: /i found the playlist/i }));

    expect(await screen.findByText(/apple music did not confirm the playlist/i)).toBeTruthy();
    expect(onSetUpdated).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /i found the playlist/i })).toHaveProperty(
      'disabled',
      false,
    );

    fireEvent.click(screen.getByRole('button', { name: /i found the playlist/i }));

    expect(await screen.findByText(/playlist confirmed/i)).toBeTruthy();
    expect(onSetUpdated).toHaveBeenCalledWith({
      status: 'exported',
      apple_music_playlist_id: 'p.savedPlaylist',
      apple_music_export_uncertain: false,
      apple_music_export_recovery_playlist_id: null,
    });
  });

  it('keeps playlist recovery retryable after a reconciliation request fails', async () => {
    mockApi.reconcileAppleMusicExport
      .mockRejectedValueOnce(new Error('Recovery service unavailable'))
      .mockResolvedValueOnce({ status: 'exported' });
    const onSetUpdated = vi.fn();
    render(
      <ExportModal
        {...baseProps}
        set={makeSet({
          apple_music_export_uncertain: true,
          apple_music_export_recovery_playlist_id: 'p.savedPlaylist',
        })}
        onSetUpdated={onSetUpdated}
      />,
    );

    fireEvent.click(await screen.findByRole('button', { name: /i found the playlist/i }));

    expect(await screen.findByText('Recovery service unavailable')).toBeTruthy();
    expect(onSetUpdated).not.toHaveBeenCalled();
    expect(screen.getByRole('textbox', { name: /playlist id/i })).toHaveProperty(
      'value',
      'p.savedPlaylist',
    );

    fireEvent.click(screen.getByRole('button', { name: /i found the playlist/i }));

    expect(await screen.findByText(/playlist confirmed/i)).toBeTruthy();
    expect(mockApi.reconcileAppleMusicExport).toHaveBeenCalledTimes(2);
    expect(onSetUpdated).toHaveBeenCalledWith({
      status: 'exported',
      apple_music_playlist_id: 'p.savedPlaylist',
      apple_music_export_uncertain: false,
      apple_music_export_recovery_playlist_id: null,
    });
  });

  it('keeps an ordinary Apple Music provider failure retryable', async () => {
    mockApi.exportPreflight.mockResolvedValue(makePreflightClean('apple_music'));
    mockApi.exportSetToAppleMusic.mockRejectedValue(new ApiError('Provider unavailable', 502));

    render(<ExportModal {...baseProps} />);
    fireEvent.click(screen.getByText('Apple Music'));
    fireEvent.click(await screen.findByRole('button', { name: /export to apple music/i }));

    expect(await screen.findByRole('button', { name: /export to apple music/i })).toBeTruthy();
    expect(screen.getByText('Provider unavailable')).toBeTruthy();
  });

  it('disables Apple Music connect while MusicKit authorization is pending', async () => {
    mockApi.exportPreflight
      .mockResolvedValueOnce({
        ...makePreflightClean('apple_music'),
        apple_music_connected: false,
      })
      .mockResolvedValueOnce({
        ...makePreflightClean('apple_music'),
        apple_music_connected: true,
      });
    mockApi.getAppleMusicDeveloperToken.mockResolvedValue({
      developer_token: 'developer-token',
      expires_at: 100,
    });
    let resolveAuthorization: (token: string) => void = () => {};
    const authorization = new Promise<string>(resolve => {
      resolveAuthorization = resolve;
    });
    const authorize = vi.fn().mockReturnValue(authorization);
    Object.defineProperty(window, 'MusicKit', {
      configurable: true,
      value: {
        configure: vi.fn().mockResolvedValue(undefined),
        getInstance: () => ({ authorize }),
      },
    });
    mockApi.linkAppleMusicAccount.mockResolvedValue({
      configured: true,
      linked: true,
      requires_reauthorization: false,
      storefront: 'gb',
    });

    render(<ExportModal {...baseProps} />);
    fireEvent.click(screen.getByText('Apple Music'));
    await waitFor(() => expect(screen.getByRole('button', { name: /connect apple music/i })).toBeTruthy());
    const connectButton = screen.getByRole('button', { name: /connect apple music/i });
    fireEvent.click(connectButton);

    const pendingButton = await screen.findByRole('button', { name: /connecting apple music/i });
    expect((pendingButton as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(pendingButton);
    expect(authorize).toHaveBeenCalledTimes(1);

    resolveAuthorization('music-user-token-secret');
    await waitFor(() => expect(mockApi.linkAppleMusicAccount).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole('button', { name: /export to apple music/i })).toBeTruthy());
  });
});
