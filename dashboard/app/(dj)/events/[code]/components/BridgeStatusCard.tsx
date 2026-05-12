'use client';

import { useState, useEffect, useCallback } from 'react';
import { api } from '@/lib/api';
import { Tooltip } from '@/components/Tooltip';

interface BridgeDetails {
  circuitBreakerState: string | null;
  bufferSize: number | null;
  pluginId: string | null;
  deckCount: number | null;
  uptimeSeconds: number | null;
}

interface BridgeStatusCardProps {
  eventCode: string;
  bridgeConnected: boolean;
  bridgeDetails?: BridgeDetails | null;
}

function formatUptime(seconds: number | null): string {
  if (seconds === null || seconds < 0) return '--';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function circuitBreakerColor(state: string | null): string {
  if (!state) return 'var(--text-tertiary)';
  switch (state.toUpperCase()) {
    case 'CLOSED':
      return 'var(--color-success)';
    case 'OPEN':
      return 'var(--color-danger)';
    case 'HALF_OPEN':
      return 'var(--color-warning)';
    default:
      return 'var(--text-tertiary)';
  }
}

type CommandType = 'ping' | 'reset_decks' | 'reconnect' | 'restart';

export function BridgeStatusCard({ eventCode, bridgeConnected, bridgeDetails }: BridgeStatusCardProps) {
  const [loadingCommand, setLoadingCommand] = useState<CommandType | null>(null);
  const [commandError, setCommandError] = useState<string | null>(null);
  const [showRestartConfirm, setShowRestartConfirm] = useState(false);

  // Auto-clear loading state after 10s (fire-and-forget)
  useEffect(() => {
    if (!loadingCommand) return;
    const timer = setTimeout(() => setLoadingCommand(null), 10_000);
    return () => clearTimeout(timer);
  }, [loadingCommand]);

  // Auto-clear error after 5s
  useEffect(() => {
    if (!commandError) return;
    const timer = setTimeout(() => setCommandError(null), 5000);
    return () => clearTimeout(timer);
  }, [commandError]);

  const sendCommand = useCallback(async (command: CommandType) => {
    setLoadingCommand(command);
    setCommandError(null);
    try {
      await api.sendBridgeCommand(eventCode, command);
    } catch (err) {
      setCommandError(err instanceof Error ? err.message : 'Command failed');
      setLoadingCommand(null);
    }
  }, [eventCode]);

  const handleRestart = useCallback(() => {
    setShowRestartConfirm(false);
    sendCommand('restart');
  }, [sendCommand]);

  const buttonStyle = (disabled: boolean): React.CSSProperties => ({
    background: 'transparent',
    border: `1px solid ${disabled ? 'var(--border)' : 'var(--border)'}`,
    color: disabled ? 'var(--text-tertiary)' : 'var(--text-secondary)',
    padding: '0.25rem 0.625rem',
    borderRadius: '0.25rem',
    fontSize: '0.75rem',
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.5 : 1,
    display: 'inline-flex',
    alignItems: 'center',
    gap: '0.375rem',
    whiteSpace: 'nowrap' as const,
  });

  const detailLabelStyle: React.CSSProperties = {
    color: 'var(--text-tertiary)',
    fontSize: '0.75rem',
  };

  const detailValueStyle: React.CSSProperties = {
    color: 'var(--text-secondary)',
    fontSize: '0.75rem',
    fontWeight: 500,
  };

  const hasDetails = bridgeConnected && bridgeDetails;

  return (
    <div className="card" style={{ marginBottom: '1rem', padding: '1rem', overflow: 'visible' }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <span style={{ fontWeight: 600 }}>Bridge Status</span>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', margin: '0.25rem 0 0' }}>
            Live track detection for compatible controllers and software
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span
            style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              background: bridgeConnected ? 'var(--color-success)' : 'var(--text-tertiary)',
              display: 'inline-block',
            }}
          />
          <span style={{ color: bridgeConnected ? 'var(--color-success)' : 'var(--text-secondary)', fontSize: '0.875rem' }}>
            {bridgeConnected ? 'Bridge Connected' : 'Bridge Not Connected'}
          </span>
        </div>
      </div>

      {/* Enriched details grid */}
      {hasDetails && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(100px, 1fr))',
            gap: '0.5rem 1rem',
            marginTop: '0.75rem',
            paddingTop: '0.625rem',
            borderTop: '1px solid var(--border-subtle)',
          }}
        >
          {bridgeDetails.pluginId && (
            <div>
              <div style={detailLabelStyle}>Plugin</div>
              <div style={detailValueStyle}>{bridgeDetails.pluginId}</div>
            </div>
          )}
          {bridgeDetails.circuitBreakerState && (
            <div>
              <div style={detailLabelStyle}>Circuit Breaker</div>
              <div style={{ ...detailValueStyle, color: circuitBreakerColor(bridgeDetails.circuitBreakerState) }}>
                {bridgeDetails.circuitBreakerState}
              </div>
            </div>
          )}
          {bridgeDetails.bufferSize !== null && (
            <div>
              <div style={detailLabelStyle}>Buffer</div>
              <div style={detailValueStyle}>{bridgeDetails.bufferSize} tracks</div>
            </div>
          )}
          {bridgeDetails.deckCount !== null && (
            <div>
              <div style={detailLabelStyle}>Decks</div>
              <div style={detailValueStyle}>{bridgeDetails.deckCount}</div>
            </div>
          )}
          {bridgeDetails.uptimeSeconds !== null && (
            <div>
              <div style={detailLabelStyle}>Uptime</div>
              <div style={detailValueStyle}>{formatUptime(bridgeDetails.uptimeSeconds)}</div>
            </div>
          )}
        </div>
      )}

      {/* Action buttons */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
          marginTop: '0.75rem',
          paddingTop: '0.625rem',
          borderTop: '1px solid var(--border-subtle)',
          flexWrap: 'wrap',
        }}
      >
        <Tooltip title="Ping Bridge" description="Sends a test ping to verify the Bridge App is responding. A green notification appears in the Bridge App when received.">
          <button
            style={buttonStyle(!bridgeConnected || loadingCommand !== null)}
            disabled={!bridgeConnected || loadingCommand !== null}
            onClick={() => sendCommand('ping')}
          >
            {loadingCommand === 'ping' && <Spinner />}
            Ping
          </button>
        </Tooltip>
        <span style={{ width: '1px', height: '16px', background: 'var(--border)', display: 'inline-block' }} />
        <Tooltip title="Reset Decks" description="Clears all tracked deck state. Use when the bridge shows phantom tracks that aren't actually on the decks. Lowest impact — doesn't touch the equipment connection.">
          <button
            style={buttonStyle(!bridgeConnected || loadingCommand !== null)}
            disabled={!bridgeConnected || loadingCommand !== null}
            onClick={() => sendCommand('reset_decks')}
          >
            {loadingCommand === 'reset_decks' && <Spinner />}
            Reset Decks
          </button>
        </Tooltip>
        <Tooltip title="Reconnect" description="Tears down and re-establishes the connection to your DJ equipment. Use when the bridge is connected but stopped receiving track updates.">
          <button
            style={buttonStyle(!bridgeConnected || loadingCommand !== null)}
            disabled={!bridgeConnected || loadingCommand !== null}
            onClick={() => sendCommand('reconnect')}
          >
            {loadingCommand === 'reconnect' && <Spinner />}
            Reconnect
          </button>
        </Tooltip>
        <Tooltip title="Restart Bridge" description="Full stop and restart of the bridge. Use as a last resort when other options don't fix the issue. Briefly disconnects from your equipment.">
          <button
            style={buttonStyle(!bridgeConnected || loadingCommand !== null)}
            disabled={!bridgeConnected || loadingCommand !== null}
            onClick={() => setShowRestartConfirm(true)}
          >
            {loadingCommand === 'restart' && <Spinner />}
            Restart
          </button>
        </Tooltip>

        {commandError && (
          <span style={{ color: 'var(--color-danger)', fontSize: '0.75rem', marginLeft: '0.25rem' }}>
            {commandError}
          </span>
        )}
      </div>

      {/* Restart confirmation dialog */}
      {showRestartConfirm && (
        <div
          style={{
            marginTop: '0.5rem',
            padding: '0.625rem 0.75rem',
            background: 'var(--card)',
            borderRadius: '0.375rem',
            border: '1px solid var(--border)',
            fontSize: '0.8125rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
            flexWrap: 'wrap',
          }}
        >
          <span style={{ color: 'var(--color-warning)' }}>
            This will briefly disconnect from your equipment. Continue?
          </span>
          <div style={{ display: 'flex', gap: '0.375rem' }}>
            <button
              style={{
                background: 'var(--color-danger)',
                color: '#fff',
                border: 'none',
                padding: '0.25rem 0.625rem',
                borderRadius: '0.25rem',
                fontSize: '0.75rem',
                cursor: 'pointer',
              }}
              onClick={handleRestart}
            >
              Restart
            </button>
            <button
              style={{
                background: 'var(--surface-raised)',
                color: 'var(--text-secondary)',
                border: 'none',
                padding: '0.25rem 0.625rem',
                borderRadius: '0.25rem',
                fontSize: '0.75rem',
                cursor: 'pointer',
              }}
              onClick={() => setShowRestartConfirm(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Spinner() {
  return (
    <span
      style={{
        display: 'inline-block',
        width: '10px',
        height: '10px',
        border: '1.5px solid var(--text-tertiary)',
        borderTopColor: 'var(--text-secondary)',
        borderRadius: '50%',
        animation: 'spin 0.6s linear infinite',
      }}
    />
  );
}
