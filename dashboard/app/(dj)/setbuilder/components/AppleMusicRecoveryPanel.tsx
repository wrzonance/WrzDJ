
import sharedStyles from '../setbuilder-shared.module.css';
import type {
  AppleMusicRecoveryAction,
  AppleMusicRecoveryResult,
  AppleMusicUnconfirmedExport,
} from './useAppleMusicRecovery';

interface AppleMusicRecoveryPanelProps {
  setName: string;
  unconfirmed: AppleMusicUnconfirmedExport | null;
  playlistId: string;
  onPlaylistIdChange: (value: string) => void;
  confirmPlaylistAbsent: boolean;
  onConfirmPlaylistAbsentChange: (confirmed: boolean) => void;
  isReconciling: boolean;
  result: AppleMusicRecoveryResult | null;
  error: string | null;
  onRecover: (action: AppleMusicRecoveryAction) => void;
}

export function AppleMusicRecoveryPanel({
  setName,
  unconfirmed,
  playlistId,
  onPlaylistIdChange,
  confirmPlaylistAbsent,
  onConfirmPlaylistAbsentChange,
  isReconciling,
  result,
  error,
  onRecover,
}: AppleMusicRecoveryPanelProps) {
  if (result) {
    return (
      <div role="status">
        <p>
          {result === 'found'
            ? 'Playlist confirmed. This set is marked as exported.'
            : 'No playlist was found. You can start a new export when you’re ready.'}
        </p>
      </div>
    );
  }

  return (
    <div role="status">
      <p>
        {unconfirmed?.message ??
          'Apple Music did not confirm whether this playlist was created.'}
      </p>
      <p>
        Check your Apple Music library for “{setName}”. Do not start another export
        until you have checked.
      </p>
      {unconfirmed?.playlistId && <p>Playlist ID: {unconfirmed.playlistId}</p>}
      {error && <div className={sharedStyles.imError}>{error}</div>}
      <label style={{ display: 'block', marginBottom: '0.5rem' }}>
        Playlist ID
        <input
          className="input"
          aria-label="Playlist ID"
          value={playlistId}
          onChange={event => onPlaylistIdChange(event.target.value)}
          disabled={isReconciling}
          style={{ display: 'block', marginTop: '0.25rem' }}
        />
      </label>
      <p style={{ fontSize: '0.6875rem', color: 'var(--text-secondary)' }}>
        Use the ID from its Apple Music link. It starts with “p.”.
      </p>
      <button
        className="btn btn-primary btn-sm"
        onClick={() => onRecover('playlist_found')}
        disabled={isReconciling || !/^p\.[A-Za-z0-9_-]{1,98}$/.test(playlistId.trim())}
      >
        {isReconciling ? 'Saving…' : 'I found the playlist'}
      </button>
      {!confirmPlaylistAbsent ? (
        <button
          className="btn btn-sm"
          onClick={() => onConfirmPlaylistAbsentChange(true)}
          disabled={isReconciling}
          style={{ marginLeft: '0.5rem' }}
        >
          I couldn&apos;t find the playlist
        </button>
      ) : (
        <div style={{ marginTop: '0.75rem' }}>
          <p>Confirm that you checked your library and did not find this playlist.</p>
          <button
            className="btn btn-sm"
            onClick={() => onRecover('playlist_absent')}
            disabled={isReconciling}
          >
            {isReconciling ? 'Saving…' : 'Yes, no playlist was found'}
          </button>
          <button
            className="btn btn-sm"
            onClick={() => onConfirmPlaylistAbsentChange(false)}
            disabled={isReconciling}
            style={{ marginLeft: '0.5rem' }}
          >
            Go back
          </button>
        </div>
      )}
    </div>
  );
}
