import type { BridgeStatus } from '../../shared/types.js';

interface StatusPanelProps {
  status: BridgeStatus;
  /** Live join code (what guests use / the dashboard shows) for display. */
  joinCode: string | null;
}

export function StatusPanel({ status, joinCode }: StatusPanelProps) {
  if (!status.isRunning) {
    return null;
  }

  return (
    <>
      {/* Backend unreachable warning */}
      {!status.backendReachable && (
        <div className="network-warning">
          <p>Backend unreachable — track updates are not being sent.</p>
        </div>
      )}

      {/* Network warnings */}
      {status.networkWarnings.length > 0 && (
        <div className="network-warning">
          {status.networkWarnings.map((warning, i) => (
            <p key={i}>{warning}</p>
          ))}
        </div>
      )}

      {/* Connection + Now Playing */}
      <div className="card">
        <div className="card-title">Status</div>

        <div className="status-grid">
          <div className="status-item">
            <div className="status-item-label">Connection</div>
            <div className="status-item-value" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span className={`status-dot ${status.connectedDevice ? 'status-dot-green' : 'status-dot-yellow'}`} />
              {status.connectedDevice || 'Waiting for device...'}
            </div>
          </div>
          <div className="status-item">
            <div className="status-item-label">Event</div>
            <div className="status-item-value">{joinCode || status.eventCode || '-'}</div>
          </div>
        </div>

        {status.currentTrack && (
          <div className="now-playing" style={{ marginTop: '0.75rem' }}>
            <div className="now-playing-info">
              <h3>{status.currentTrack.title}</h3>
              <p>
                {status.currentTrack.artist}
                {status.currentTrack.album && ` — ${status.currentTrack.album}`}
                {' '}
                <span style={{ color: '#666' }}>Deck {status.currentTrack.deckId}</span>
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Deck States */}
      {status.deckStates.length > 0 && (
        <div className="card">
          <div className="card-title">Decks</div>
          <div className="deck-grid">
            {status.deckStates.map((deck) => (
              <div key={deck.deckId} className="deck-card">
                <div className="deck-card-id">
                  Deck {deck.deckId}
                  {deck.isMaster && ' ★'}
                </div>
                <div className={`deck-card-state ${deck.state}`}>
                  {deck.state}
                </div>
                {deck.trackTitle && (
                  <div className="deck-card-track">{deck.trackTitle}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
