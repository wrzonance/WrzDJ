import { useState } from 'react';
import { api } from '@/lib/api';
import type { ExportAppleMusicRecoveryRequest, SetDetail } from '@/lib/api/types';

export type AppleMusicRecoveryAction = 'playlist_found' | 'playlist_absent';
export type AppleMusicRecoveryResult = 'found' | 'absent';

export interface AppleMusicUnconfirmedExport {
  message: string;
  playlistId: string | null;
}

interface UseAppleMusicRecoveryOptions {
  set: SetDetail;
  onSetUpdated: (patch: Partial<SetDetail>) => void;
  onRecovered: () => void;
}

const DEFAULT_UNCONFIRMED_MESSAGE = 'Apple Music did not confirm whether this playlist was created.';

export function useAppleMusicRecovery({ set, onSetUpdated, onRecovered }: UseAppleMusicRecoveryOptions) {
  const [unconfirmed, setUnconfirmed] = useState<AppleMusicUnconfirmedExport | null>(
    set.apple_music_export_uncertain
      ? { message: DEFAULT_UNCONFIRMED_MESSAGE, playlistId: set.apple_music_export_recovery_playlist_id }
      : null,
  );
  const [playlistId, setPlaylistId] = useState(set.apple_music_export_recovery_playlist_id ?? '');
  const [confirmPlaylistAbsent, setConfirmPlaylistAbsent] = useState(false);
  const [isReconciling, setIsReconciling] = useState(false);
  const [result, setResult] = useState<AppleMusicRecoveryResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const begin = (nextUnconfirmed: AppleMusicUnconfirmedExport) => {
    setUnconfirmed(nextUnconfirmed);
    setPlaylistId(nextUnconfirmed.playlistId ?? '');
    setConfirmPlaylistAbsent(false);
    setResult(null);
    setError(null);
    onSetUpdated({
      apple_music_export_uncertain: true,
      apple_music_export_recovery_playlist_id: nextUnconfirmed.playlistId,
    });
  };

  const reset = () => {
    setUnconfirmed(null);
    setPlaylistId('');
    setConfirmPlaylistAbsent(false);
    setIsReconciling(false);
    setResult(null);
    setError(null);
  };

  const reconcile = async (action: AppleMusicRecoveryAction) => {
    const normalizedPlaylistId = playlistId.trim();
    if (action === 'playlist_found' && !/^p\.[A-Za-z0-9_-]{1,98}$/.test(normalizedPlaylistId)) return;

    setError(null);
    setIsReconciling(true);
    try {
      const request: ExportAppleMusicRecoveryRequest = action === 'playlist_found'
        ? { action, playlist_id: normalizedPlaylistId }
        : { action };
      const response = await api.reconcileAppleMusicExport(set.id, request);
      if (action === 'playlist_found' && response.status !== 'exported') {
        throw new Error('Apple Music did not confirm the playlist. Please check again.');
      }
      if (action === 'playlist_absent' && response.status !== 'ready_to_retry') {
        throw new Error('Apple Music could not update the export status. Please try again.');
      }

      if (action === 'playlist_found') {
        onSetUpdated({
          status: 'exported',
          apple_music_playlist_id: normalizedPlaylistId,
          apple_music_export_uncertain: false,
          apple_music_export_recovery_playlist_id: null,
        });
        setResult('found');
      } else {
        onSetUpdated({
          apple_music_export_uncertain: false,
          apple_music_export_recovery_playlist_id: null,
        });
        setResult('absent');
      }
      onRecovered();
    } catch (cause) {
      setError(
        cause instanceof Error && cause.message
          ? cause.message
          : 'Export failed — try again',
      );
    } finally {
      setIsReconciling(false);
    }
  };

  return {
    unconfirmed,
    playlistId,
    setPlaylistId,
    confirmPlaylistAbsent,
    setConfirmPlaylistAbsent,
    isReconciling,
    result,
    error,
    begin,
    reset,
    reconcile,
  };
}
