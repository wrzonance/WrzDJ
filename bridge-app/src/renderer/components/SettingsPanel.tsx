import { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';
import { DEFAULT_SETTINGS, type BridgeSettings, type PluginMeta } from '../../shared/types.js';
import { useBridgeStatus } from '../hooks/useBridgeStatus.js';
import { SettingsFields } from './SettingsFields.js';

export function SettingsPanel() {
  const [settings, setSettings] = useState<BridgeSettings>(DEFAULT_SETTINGS);
  const [plugins, setPlugins] = useState<readonly PluginMeta[]>([]);
  const [open, setOpen] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const bridgeStatus = useBridgeStatus();

  useEffect(() => {
    api.getSettings().then(setSettings).catch((error: unknown) => {
      setSaveError(error instanceof Error ? error.message : 'Failed to load settings');
    });
    api.listPluginMeta().then(setPlugins).catch(() => {
      // Plugin discovery is optional for the rest of the settings panel.
    });
  }, []);

  const saveSettings = useCallback(async (partial: Partial<BridgeSettings>) => {
    setSaveError(null);
    try {
      setSettings(await api.updateSettings(partial));
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : 'Failed to save settings');
    }
  }, []);

  return (
    <div className="card">
      <div
        className="card-title"
        style={{ cursor: 'pointer', display: 'flex', justifyContent: 'space-between' }}
        onClick={() => setOpen(!open)}
      >
        Detection Settings
        <span style={{ fontSize: '0.75rem' }}>{open ? '▼' : '▶'}</span>
      </div>

      {saveError && <div className="error-message" style={{ marginBottom: '0.5rem' }}>{saveError}</div>}
      {open && (
        <SettingsFields
          settings={settings}
          plugins={plugins}
          disabled={bridgeStatus.isRunning}
          onChange={saveSettings}
        />
      )}
    </div>
  );
}
