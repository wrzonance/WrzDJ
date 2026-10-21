import type { BridgeSettings, PluginMeta, PluginConfigOption } from '../../shared/types.js';

interface SettingsFieldsProps {
  settings: BridgeSettings;
  plugins: readonly PluginMeta[];
  disabled: boolean;
  onChange: (partial: Partial<BridgeSettings>) => void;
}

export function SettingsFields({ settings, plugins, disabled, onChange }: SettingsFieldsProps) {
  const protocol = settings.protocol || 'stagelinq';
  const currentPlugin = plugins.find((plugin) => plugin.info.id === protocol);

  return (
    <>
      <div className="settings-row">
        <label>Protocol</label>
        <select
          value={protocol}
          disabled={disabled}
          onChange={(event) => onChange({ protocol: event.target.value })}
          style={{
            background: 'var(--color-input-background)',
            color: 'var(--color-text)',
            border: '1px solid var(--color-border)',
            borderRadius: '4px',
            padding: '4px 8px',
            fontSize: '0.85rem',
          }}
        >
          {plugins.map((plugin) => (
            <option key={plugin.info.id} value={plugin.info.id}>{plugin.info.name}</option>
          ))}
        </select>
      </div>

      {disabled && (
        <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', marginBottom: '8px', paddingLeft: '4px' }}>
          Stop the bridge to change protocol.
        </div>
      )}

      {currentPlugin?.configOptions.map((option) => (
        <PluginConfigInput
          key={option.key}
          option={option}
          value={settings.pluginConfig?.[option.key]}
          disabled={disabled}
          onChange={(value) => onChange({
            pluginConfig: { ...settings.pluginConfig, [option.key]: value },
          })}
        />
      ))}

      <div className="settings-row">
        <label>Live threshold (seconds)</label>
        <input
          type="number"
          value={settings.liveThresholdSeconds}
          min={1}
          max={60}
          onChange={(event) => onChange({ liveThresholdSeconds: parseInt(event.target.value) || 15 })}
        />
      </div>
      <div className="settings-row">
        <label>Pause grace (seconds)</label>
        <input
          type="number"
          value={settings.pauseGraceSeconds}
          min={1}
          max={30}
          onChange={(event) => onChange({ pauseGraceSeconds: parseInt(event.target.value) || 3 })}
        />
      </div>
      <div className="settings-row">
        <label>Now-playing pause (seconds)</label>
        <input
          type="number"
          value={settings.nowPlayingPauseSeconds}
          min={1}
          max={60}
          onChange={(event) => onChange({ nowPlayingPauseSeconds: parseInt(event.target.value) || 10 })}
        />
      </div>
      <div className="settings-row">
        <label>Min play (seconds)</label>
        <input
          type="number"
          value={settings.minPlaySeconds}
          min={1}
          max={30}
          onChange={(event) => onChange({ minPlaySeconds: parseInt(event.target.value) || 5 })}
        />
      </div>

      {currentPlugin?.capabilities.faderLevel && (
        <div className="settings-row">
          <label>Require fader up</label>
          <button
            className={`toggle ${settings.useFaderDetection ? 'active' : ''}`}
            disabled={disabled}
            onClick={() => onChange({ useFaderDetection: !settings.useFaderDetection })}
          />
        </div>
      )}
      {currentPlugin?.capabilities.masterDeck && (
        <div className="settings-row">
          <label>Master deck only</label>
          <button
            className={`toggle ${settings.masterDeckPriority ? 'active' : ''}`}
            disabled={disabled}
            onClick={() => onChange({ masterDeckPriority: !settings.masterDeckPriority })}
          />
        </div>
      )}
    </>
  );
}

function PluginConfigInput({ option, value, disabled, onChange }: {
  option: PluginConfigOption;
  value: unknown;
  disabled: boolean;
  onChange: (value: number | string | boolean) => void;
}) {
  if (option.type === 'number') {
    const defaultValue = typeof option.default === 'number' && Number.isFinite(option.default)
      ? option.default
      : option.min ?? 0;
    const currentValue = typeof value === 'number' && Number.isFinite(value)
      ? value
      : defaultValue;
    return (
      <div className="settings-row">
        <label>{option.label}</label>
        <input
          type="number"
          value={currentValue}
          min={option.min}
          max={option.max}
          disabled={disabled}
          onChange={(event) => {
            const parsedValue = parseInt(event.target.value, 10);
            onChange(Number.isNaN(parsedValue) ? defaultValue : parsedValue);
          }}
        />
      </div>
    );
  }
  if (option.type === 'string') {
    const defaultValue = typeof option.default === 'string' ? option.default : '';
    const currentValue = typeof value === 'string' ? value : defaultValue;
    return (
      <div className="settings-row">
        <label>{option.label}</label>
        <input
          type="text"
          value={currentValue}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        />
      </div>
    );
  }
  if (option.type === 'boolean') {
    const defaultValue = typeof option.default === 'boolean' ? option.default : false;
    const checked = typeof value === 'boolean' ? value : defaultValue;
    return (
      <div className="settings-row">
        <label>{option.label}</label>
        <button
          className={`toggle ${checked ? 'active' : ''}`}
          disabled={disabled}
          onClick={() => onChange(!checked)}
        />
      </div>
    );
  }
  return null;
}
