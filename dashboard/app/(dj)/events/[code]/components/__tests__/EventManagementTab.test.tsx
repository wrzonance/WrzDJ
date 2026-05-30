import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { EventManagementTab } from '../EventManagementTab';

vi.mock('@/lib/help/HelpContext', () => ({
  useHelp: () => ({
    helpMode: false, onboardingActive: false, currentStep: 0, activeSpotId: null,
    toggleHelpMode: vi.fn(), registerSpot: vi.fn(() => vi.fn()),
    getSpotsForPage: vi.fn(() => []), startOnboarding: vi.fn(),
    nextStep: vi.fn(), prevStep: vi.fn(), skipOnboarding: vi.fn(),
    hasSeenPage: vi.fn(() => false),
  }),
}));

vi.mock('../KioskControlsCard', () => ({
  KioskControlsCard: ({
    frictionlessJoin,
    onToggleFrictionless,
  }: {
    frictionlessJoin: boolean;
    onToggleFrictionless: () => void;
  }) => (
    <div data-testid="kiosk-controls">
      KioskControls
      <button type="button" onClick={onToggleFrictionless}>
        Frictionless join: {frictionlessJoin ? 'On' : 'Off'}
      </button>
    </div>
  ),
}));

vi.mock('../StreamOverlayCard', () => ({
  StreamOverlayCard: () => <div data-testid="stream-overlay">StreamOverlay</div>,
}));

vi.mock('../BridgeStatusCard', () => ({
  BridgeStatusCard: () => <div data-testid="bridge-status">BridgeStatus</div>,
}));

vi.mock('../CloudProvidersCard', () => ({
  CloudProvidersCard: () => <div data-testid="cloud-providers">CloudProviders</div>,
}));

vi.mock('../EventCustomizationCard', () => ({
  EventCustomizationCard: () => <div data-testid="event-customization">EventCustomization</div>,
}));

const baseProps = {
  code: 'ABC123',
  event: { id: 1, name: 'Test', code: 'ABC123', is_active: true, expires_at: '', created_at: '', requests_open: true, now_playing_hidden: false, auto_hide_minutes: 10 } as never,
  bridgeConnected: false,
  bridgeDetails: null,
  requestsOpen: true,
  togglingRequests: false,
  onToggleRequests: vi.fn(),
  nowPlayingHidden: false,
  togglingNowPlaying: false,
  onToggleNowPlaying: vi.fn(),
  autoHideInput: '10',
  autoHideMinutes: 10,
  savingAutoHide: false,
  onAutoHideInputChange: vi.fn(),
  onSaveAutoHide: vi.fn(),
  tidalStatus: null,
  tidalSyncEnabled: false,
  togglingTidalSync: false,
  onToggleTidalSync: vi.fn(),
  onConnectTidal: vi.fn(),
  onDisconnectTidal: vi.fn(),
  beatportStatus: null,
  beatportSyncEnabled: false,
  togglingBeatportSync: false,
  onToggleBeatportSync: vi.fn(),
  onConnectBeatport: vi.fn(),
  onDisconnectBeatport: vi.fn(),
  kioskDisplayOnly: false,
  togglingDisplayOnly: false,
  onToggleDisplayOnly: vi.fn(),
  frictionlessJoin: false,
  togglingFrictionless: false,
  onToggleFrictionless: vi.fn(),
  uploadingBanner: false,
  onBannerSelect: vi.fn(),
  onDeleteBanner: vi.fn(),
  onPreEventEnabled: vi.fn(),
  onJumpToPreEventTab: vi.fn(),
};

describe('EventManagementTab', () => {
  it('renders KioskControlsCard', () => {
    render(<EventManagementTab {...baseProps} />);
    expect(screen.getByTestId('kiosk-controls')).toBeInTheDocument();
  });

  it('renders StreamOverlayCard', () => {
    render(<EventManagementTab {...baseProps} />);
    expect(screen.getByTestId('stream-overlay')).toBeInTheDocument();
  });

  it('renders BridgeStatusCard', () => {
    render(<EventManagementTab {...baseProps} />);
    expect(screen.getByTestId('bridge-status')).toBeInTheDocument();
  });

  it('renders CloudProvidersCard', () => {
    render(<EventManagementTab {...baseProps} />);
    expect(screen.getByTestId('cloud-providers')).toBeInTheDocument();
  });

  it('renders EventCustomizationCard', () => {
    render(<EventManagementTab {...baseProps} />);
    expect(screen.getByTestId('event-customization')).toBeInTheDocument();
  });

  it('renders Frictionless join toggle and fires handler', () => {
    const onToggleFrictionless = vi.fn();
    render(
      <EventManagementTab
        {...baseProps}
        frictionlessJoin={false}
        togglingFrictionless={false}
        onToggleFrictionless={onToggleFrictionless}
      />
    );
    fireEvent.click(screen.getByText(/Frictionless join/i));
    expect(onToggleFrictionless).toHaveBeenCalled();
  });
});
