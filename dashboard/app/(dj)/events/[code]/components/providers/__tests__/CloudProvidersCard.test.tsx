import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CloudProvidersCard } from '../CloudProvidersCard';
import type { BeatportStatus, TidalStatus } from '@/lib/api/types';

const tidal: TidalStatus = {
  expires_at: null,
  integration_enabled: true,
  linked: true,
  user_id: 'tidal-user',
};
const beatport: BeatportStatus = {
  configured: true,
  expires_at: null,
  integration_enabled: true,
  linked: true,
  subscription: 'bp_pro',
};

function renderCard(overrides: Partial<React.ComponentProps<typeof CloudProvidersCard>> = {}) {
  const callbacks = {
    onToggleTidalSync: vi.fn(),
    onConnectTidal: vi.fn(),
    onDisconnectTidal: vi.fn(),
    onToggleBeatportSync: vi.fn(),
    onConnectBeatport: vi.fn(),
    onDisconnectBeatport: vi.fn(),
  };
  render(
    <CloudProvidersCard
      tidalStatus={null}
      tidalSyncEnabled={false}
      togglingTidalSync={false}
      beatportStatus={null}
      beatportSyncEnabled={false}
      togglingBeatportSync={false}
      {...callbacks}
      {...overrides}
    />,
  );
  return callbacks;
}

describe('CloudProvidersCard', () => {
  it('offers account connection when providers are not linked', () => {
    const callbacks = renderCard();

    const tidalButton = screen.getByRole('button', { name: 'Connect Tidal' });
    const beatportButton = screen.getByRole('button', { name: 'Connect Beatport' });
    expect(tidalButton.style.background).toBe('rgb(0, 102, 255)');
    expect(beatportButton.style.background).toBe('rgb(1, 255, 40)');
    expect(beatportButton.style.color).toBe('var(--text-on-bright-accent)');

    fireEvent.click(tidalButton);
    fireEvent.click(beatportButton);

    expect(callbacks.onConnectTidal).toHaveBeenCalledOnce();
    expect(callbacks.onConnectBeatport).toHaveBeenCalledOnce();
  });

  it('shows unavailable integrations without offering account actions', () => {
    renderCard({
      tidalStatus: { ...tidal, integration_enabled: false },
      beatportStatus: { ...beatport, integration_enabled: false },
    });

    expect(screen.getAllByText('Unavailable')).toHaveLength(2);
    expect(screen.queryByRole('button', { name: 'Connect Tidal' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Disconnect' })).not.toBeInTheDocument();
  });

  it('shows linked account capabilities and delegates sync toggles', () => {
    const callbacks = renderCard({
      tidalStatus: tidal,
      tidalSyncEnabled: true,
      beatportStatus: beatport,
      beatportSyncEnabled: false,
    });

    expect(screen.getAllByText('Connected')).toHaveLength(2);
    expect(screen.getByText('Full Streaming Access')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Enabled' }));
    fireEvent.click(screen.getByRole('button', { name: 'Disabled' }));

    expect(callbacks.onToggleTidalSync).toHaveBeenCalledOnce();
    expect(callbacks.onToggleBeatportSync).toHaveBeenCalledOnce();
  });

  it('distinguishes a purchased-only Beatport account and blocks a busy toggle', () => {
    renderCard({
      beatportStatus: { ...beatport, subscription: null },
      togglingBeatportSync: true,
    });

    expect(screen.getByText('Purchased Library Only')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '...' })).toBeDisabled();
  });
});
