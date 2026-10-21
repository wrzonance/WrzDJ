import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import AppleMusicAccountCard from '../AppleMusicAccountCard';

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAppleMusicStatus: vi.fn(),
    getAppleMusicDeveloperToken: vi.fn(),
    linkAppleMusicAccount: vi.fn(),
    disconnectAppleMusicAccount: vi.fn(),
  },
}));

vi.mock('@/lib/api', () => ({ api: mockApi }));

describe('AppleMusicAccountCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.MusicKit = {
      configure: vi.fn().mockResolvedValue(undefined),
      getInstance: () => ({ authorize: vi.fn().mockResolvedValue('music-user-token-secret') }),
    } as never;
  });

  it('explains when Apple Music deployment credentials are missing', async () => {
    mockApi.getAppleMusicStatus.mockResolvedValue({
      configured: false,
      linked: false,
      requires_reauthorization: false,
      storefront: null,
    });

    render(<AppleMusicAccountCard />);

    expect(await screen.findByText('Apple Music is not configured for this deployment.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Connect Apple Music' })).toHaveProperty('disabled', true);
  });

  it('uses MusicKit to authorize, then sends the user token to the server', async () => {
    mockApi.getAppleMusicStatus.mockResolvedValue({
      configured: true,
      linked: false,
      requires_reauthorization: false,
      storefront: null,
    });
    mockApi.getAppleMusicDeveloperToken.mockResolvedValue({
      developer_token: 'short-lived-developer-token',
      expires_at: 1800000900,
    });
    mockApi.linkAppleMusicAccount.mockResolvedValue({
      configured: true,
      linked: true,
      requires_reauthorization: false,
      storefront: 'us',
    });

    render(<AppleMusicAccountCard />);
    fireEvent.click(await screen.findByRole('button', { name: 'Connect Apple Music' }));

    await waitFor(() => expect(mockApi.linkAppleMusicAccount).toHaveBeenCalledWith('music-user-token-secret'));
    expect(window.MusicKit?.configure).toHaveBeenCalledWith({
      developerToken: 'short-lived-developer-token',
      app: { name: 'WrzDJ', build: '1.0.0' },
    });
    expect(await screen.findByText('Connected to Apple Music (US).')).toBeTruthy();
    expect(screen.queryByText('music-user-token-secret')).toBeNull();
  });

  it('waits for the MusicKit initialization event after the script loads', async () => {
    window.MusicKit = undefined;
    mockApi.getAppleMusicStatus.mockResolvedValue({
      configured: true,
      linked: false,
      requires_reauthorization: false,
      storefront: null,
    });
    mockApi.getAppleMusicDeveloperToken.mockResolvedValue({
      developer_token: 'short-lived-developer-token',
      expires_at: 1800000900,
    });
    mockApi.linkAppleMusicAccount.mockResolvedValue({
      configured: true,
      linked: true,
      requires_reauthorization: false,
      storefront: 'us',
    });

    render(<AppleMusicAccountCard />);
    fireEvent.click(await screen.findByRole('button', { name: 'Connect Apple Music' }));
    const script = await waitFor(() => {
      const loadedScript = document.querySelector<HTMLScriptElement>(
        'script[src="https://js-cdn.music.apple.com/musickit/v3/musickit.js"]',
      );
      expect(loadedScript).toBeTruthy();
      return loadedScript;
    });
    fireEvent.load(script!);
    window.MusicKit = {
      configure: vi.fn().mockResolvedValue(undefined),
      getInstance: () => ({ authorize: vi.fn().mockResolvedValue('music-user-token-secret') }),
    } as never;
    document.dispatchEvent(new Event('musickitloaded'));

    await waitFor(() => expect(mockApi.linkAppleMusicAccount).toHaveBeenCalledWith('music-user-token-secret'));
  });
});
