'use client';

interface KioskControlsCardProps {
  code: string;        // collection code (DJ-side identifier; kept for legacy uses)
  joinCode: string;    // join_code — used for the public /e/{join_code}/display URL
  requestsOpen: boolean;
  togglingRequests: boolean;
  onToggleRequests: () => void;
  nowPlayingHidden: boolean;
  togglingNowPlaying: boolean;
  onToggleNowPlaying: () => void;
  autoHideInput: string;
  autoHideMinutes: number;
  savingAutoHide: boolean;
  onAutoHideInputChange: (value: string) => void;
  onSaveAutoHide: () => void;
  kioskDisplayOnly: boolean;
  togglingDisplayOnly: boolean;
  onToggleDisplayOnly: () => void;
  frictionlessJoin: boolean;
  togglingFrictionless: boolean;
  onToggleFrictionless: () => void;
}

export function KioskControlsCard({
  code: _code,
  joinCode,
  requestsOpen,
  togglingRequests,
  onToggleRequests,
  nowPlayingHidden,
  togglingNowPlaying,
  onToggleNowPlaying,
  autoHideInput,
  autoHideMinutes,
  savingAutoHide,
  onAutoHideInputChange,
  onSaveAutoHide,
  kioskDisplayOnly,
  togglingDisplayOnly,
  onToggleDisplayOnly,
  frictionlessJoin,
  togglingFrictionless,
  onToggleFrictionless,
}: KioskControlsCardProps) {
  return (
    <div className="card" style={{ marginBottom: '1rem', padding: '1rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
        <div>
          <span style={{ fontWeight: 600 }}>Kiosk Controls</span>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', margin: '0.25rem 0 0' }}>
            Control what guests see on the kiosk display
          </p>
        </div>
        <a
          href={`/e/${joinCode}/display`}
          target="_blank"
          rel="noopener noreferrer"
          className="btn btn-sm"
          style={{ background: 'var(--surface-raised)', textDecoration: 'none', color: 'var(--text)' }}
        >
          Preview Kiosk
        </a>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
        <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>Requests:</span>
        <button
          className={`btn btn-sm ${requestsOpen ? 'btn-success' : 'btn-danger'}`}
          style={{ minWidth: '100px' }}
          onClick={onToggleRequests}
          disabled={togglingRequests}
        >
          {togglingRequests ? '...' : requestsOpen ? 'Open' : 'Closed'}
        </button>
        <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>Now Playing:</span>
        <button
          className={`btn btn-sm ${nowPlayingHidden ? 'btn-danger' : 'btn-success'}`}
          style={{ minWidth: '100px' }}
          onClick={onToggleNowPlaying}
          disabled={togglingNowPlaying}
        >
          {togglingNowPlaying ? '...' : nowPlayingHidden ? 'Hidden' : 'Visible'}
        </button>
        <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>Display Only:</span>
        <button
          className={`btn btn-sm ${kioskDisplayOnly ? 'btn-primary' : ''}`}
          style={{ minWidth: '100px', background: kioskDisplayOnly ? undefined : 'var(--surface-raised)' }}
          onClick={onToggleDisplayOnly}
          disabled={togglingDisplayOnly}
        >
          {togglingDisplayOnly ? '...' : kioskDisplayOnly ? 'On' : 'Off'}
        </button>
      </div>

      {/* Frictionless join */}
      <div style={{ borderTop: '1px solid var(--border)', paddingTop: '1rem', marginBottom: '1rem' }}>
        <button
          type="button"
          className={`btn btn-sm ${frictionlessJoin ? 'btn-primary' : ''}`}
          style={{ minWidth: '180px', background: frictionlessJoin ? undefined : 'var(--surface-raised)' }}
          disabled={togglingFrictionless}
          onClick={onToggleFrictionless}
        >
          {togglingFrictionless ? '...' : `Frictionless join: ${frictionlessJoin ? 'On' : 'Off'}`}
        </button>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.8125rem', margin: '0.5rem 0 0' }}>
          Guests skip the nickname/email step and get an auto-generated name. Good for weddings &amp; private parties.
        </p>
      </div>

      {/* Auto-hide timeout */}
      <div style={{ borderTop: '1px solid var(--border)', paddingTop: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>Auto-hide Now Playing after</span>
          <input
            type="number"
            min={1}
            max={1440}
            value={autoHideInput}
            onChange={(e) => onAutoHideInputChange(e.target.value)}
            style={{
              width: '70px',
              padding: '0.25rem 0.5rem',
              background: 'var(--border-subtle)',
              border: '1px solid var(--border)',
              borderRadius: '4px',
              color: 'var(--text)',
              fontSize: '0.875rem',
              textAlign: 'center',
            }}
          />
          <span style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>minutes of inactivity</span>
          {parseInt(autoHideInput, 10) !== autoHideMinutes && (
            <button
              className="btn btn-sm btn-primary"
              onClick={onSaveAutoHide}
              disabled={savingAutoHide || isNaN(parseInt(autoHideInput, 10)) || parseInt(autoHideInput, 10) < 1 || parseInt(autoHideInput, 10) > 1440}
            >
              {savingAutoHide ? '...' : 'Save'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
