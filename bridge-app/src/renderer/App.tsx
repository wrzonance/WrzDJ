import { useState, useCallback, useEffect } from 'react';
import { useAuth } from './hooks/useAuth.js';
import { useBridgeStatus } from './hooks/useBridgeStatus.js';
import { useBridgeLog } from './hooks/useBridgeLog.js';
import { LoginForm } from './components/LoginForm.js';
import { EventSelector } from './components/EventSelector.js';
import { BridgeControls } from './components/BridgeControls.js';
import { StatusPanel } from './components/StatusPanel.js';
import { SettingsPanel } from './components/SettingsPanel.js';
import { LogPanel } from './components/LogPanel.js';
import type { EventInfo } from '../shared/types.js';

export function App() {
  const { authState, loading, error, login, logout } = useAuth();
  const bridgeStatus = useBridgeStatus();
  const { entries: logEntries, clear: clearLog } = useBridgeLog();
  const [selectedEvent, setSelectedEvent] = useState<EventInfo | null>(null);
  const [pingVisible, setPingVisible] = useState(false);

  useEffect(() => {
    const cleanup = window.bridgeApi.onPing(() => {
      setPingVisible(true);
      setTimeout(() => setPingVisible(false), 3000);
    });
    return cleanup;
  }, []);

  const handleEventSelect = useCallback((event: EventInfo) => {
    setSelectedEvent(event);
  }, []);

  const handleEventRemoved = useCallback((code: string) => {
    setSelectedEvent((prev) => (prev?.code === code ? null : prev));
  }, []);

  // Loading state
  if (loading && !authState.isAuthenticated) {
    return <div className="loading">Loading...</div>;
  }

  // Not authenticated - show login
  if (!authState.isAuthenticated) {
    return <LoginForm onLogin={login} error={error} loading={loading} />;
  }

  // Authenticated - show main UI
  return (
    <div className="app">
      {pingVisible && (
        <div className="ping-toast">
          Ping received from WrzDJ dashboard
        </div>
      )}
      <div className="app-header">
        <h1>WrzDJ Bridge</h1>
        <div className="app-header-user">
          <span>{authState.username}</span>
          <button className="btn btn-ghost btn-sm" onClick={logout}>
            Sign Out
          </button>
        </div>
      </div>

      <div className="app-content">
        <EventSelector
          selectedCode={selectedEvent?.code ?? null}
          onSelect={handleEventSelect}
          onEventRemoved={handleEventRemoved}
        />

        <BridgeControls
          status={bridgeStatus}
          selectedEventCode={selectedEvent?.code ?? null}
          joinCode={selectedEvent?.joinCode ?? null}
        />

        <StatusPanel status={bridgeStatus} joinCode={selectedEvent?.joinCode ?? null} />

        <LogPanel entries={logEntries} onClear={clearLog} />

        <SettingsPanel />
      </div>
    </div>
  );
}
