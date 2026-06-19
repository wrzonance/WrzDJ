import { useState } from 'react';
import { api } from '../api.js';
import type { BridgeStatus } from '../../shared/types.js';

interface BridgeControlsProps {
  status: BridgeStatus;
  selectedEventCode: string | null;
  /** Live join code (what guests use / the dashboard shows) for display. */
  joinCode: string | null;
}

export function BridgeControls({ status, selectedEventCode, joinCode }: BridgeControlsProps) {
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const busy = starting || stopping;

  const handleStart = async () => {
    if (!selectedEventCode || busy) return;

    setStarting(true);
    setError(null);
    try {
      await api.startBridge(selectedEventCode);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start bridge');
    } finally {
      setStarting(false);
    }
  };

  const handleStop = async () => {
    if (busy) return;

    setStopping(true);
    setError(null);
    try {
      await api.stopBridge();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to stop bridge');
    } finally {
      setStopping(false);
    }
  };

  return (
    <div className="card">
      <div className="card-title">Bridge Controls</div>

      {error && <div className="error-message">{error}</div>}

      {status.stopReason && !status.isRunning && (
        <div style={{ color: '#f59e0b', fontSize: '0.8rem', marginBottom: '0.5rem', padding: '6px 8px', background: '#2a2000', borderRadius: '4px' }}>
          Bridge stopped: {status.stopReason}
        </div>
      )}

      {!status.isRunning ? (
        <>
          <div className="bridge-controls">
            <button
              className="btn btn-success"
              onClick={handleStart}
              disabled={busy || !selectedEventCode}
            >
              {starting ? 'Starting...' : 'Start Bridge'}
            </button>
          </div>
          {!selectedEventCode && (
            <p style={{ color: '#f59e0b', fontSize: '0.8rem', marginTop: '0.5rem' }}>
              Select an event above to start the bridge.
            </p>
          )}
        </>
      ) : (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span className="status-dot status-dot-green" />
            <span>Running for event <strong>{joinCode ?? status.eventCode}</strong></span>
          </div>
          <button className="btn btn-danger btn-sm" onClick={handleStop} disabled={busy}>
            {stopping ? 'Stopping...' : 'Stop Bridge'}
          </button>
        </div>
      )}
    </div>
  );
}
