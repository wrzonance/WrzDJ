'use client';

import { useState } from 'react';
import { api, SystemSettings } from '@/lib/api';
import { useAdminPage } from '@/lib/useAdminPage';
import { HelpSpot } from '@/components/help/HelpSpot';
import { HelpButton } from '@/components/help/HelpButton';
import { OnboardingOverlay } from '@/components/help/OnboardingOverlay';

const PAGE_ID = 'admin-settings';

export default function AdminSettingsPage() {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const { data: settings, loading, error: loadError, setData: setSettings } = useAdminPage<SystemSettings>({
    pageId: PAGE_ID,
    loader: () => api.getAdminSettings(),
    onError: () => 'Failed to load settings',
  });

  const handleSave = async () => {
    if (!settings) return;
    setSaving(true);
    setError('');
    setSuccess('');
    try {
      const updated = await api.updateAdminSettings(settings);
      setSettings(updated);
      setSuccess('Settings saved');
      setTimeout(() => setSuccess(''), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="container">
        <div className="loading">Loading settings...</div>
      </div>
    );
  }

  if (!settings) {
    return (
      <div className="container">
        <div className="card" style={{ color: 'var(--color-danger)' }}>{error || loadError || 'Failed to load'}</div>
      </div>
    );
  }

  return (
    <div className="container">
      <HelpButton page={PAGE_ID} />
      <OnboardingOverlay page={PAGE_ID} />
      <h1 style={{ marginBottom: '2rem' }}>System Settings</h1>

      {(error || loadError) && (
        <div style={{ color: 'var(--color-danger)', marginBottom: '1rem' }}>{error || loadError}</div>
      )}
      {success && (
        <div style={{ color: 'var(--color-success)', marginBottom: '1rem' }}>{success}</div>
      )}

      <div className="card">
        <HelpSpot spotId="admin-registration" page={PAGE_ID} order={1} title="Self-Registration" description="Allow public sign-ups. New users start as &quot;pending&quot; until approved.">
          <div className="form-group">
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={settings.registration_enabled}
                onChange={(e) => setSettings({ ...settings, registration_enabled: e.target.checked })}
                style={{ width: '1.25rem', height: '1.25rem' }}
              />
              <div>
                <div style={{ fontWeight: 500 }}>Self-Registration</div>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                  Allow new users to register. They start as &quot;pending&quot; until approved.
                </div>
              </div>
            </label>
          </div>
        </HelpSpot>

        <HelpSpot spotId="admin-human-verification" page={PAGE_ID} order={2} title="Human Verification" description="Require guests to complete a Turnstile CAPTCHA before interacting.">
          <div className="form-group" style={{ marginTop: '1.5rem' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={settings.human_verification_enforced}
                onChange={(e) => setSettings({ ...settings, human_verification_enforced: e.target.checked })}
                style={{ width: '1.25rem', height: '1.25rem' }}
              />
              <div>
                <div style={{ fontWeight: 500 }}>Enforce human verification on guest pages</div>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                  When ON, guests must complete a Cloudflare Turnstile check before submitting requests, voting, or searching. Default OFF (soft mode logs warnings only).
                </div>
              </div>
            </label>
          </div>
        </HelpSpot>

        <HelpSpot spotId="admin-rate-limit" page={PAGE_ID} order={3} title="Search Rate Limit" description="Throttle music search queries per IP to prevent API abuse.">
          <div className="form-group" style={{ marginTop: '1.5rem' }}>
            <label htmlFor="rate-limit">Search Rate Limit (per minute per IP)</label>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '0.5rem' }}>
              Controls how many Spotify/Tidal search queries each IP can make per minute.
            </div>
            <input
              id="rate-limit"
              type="number"
              className="input"
              style={{ maxWidth: '200px' }}
              min={1}
              max={100}
              value={settings.search_rate_limit_per_minute}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  search_rate_limit_per_minute: parseInt(e.target.value) || 1,
                })
              }
            />
          </div>
        </HelpSpot>

        <HelpSpot spotId="admin-save-settings" page={PAGE_ID} order={4} title="Save" description="Settings are stored in the database and take effect immediately.">
          <button
            className="btn btn-primary"
            style={{ marginTop: '1.5rem' }}
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
        </HelpSpot>
      </div>
    </div>
  );
}
