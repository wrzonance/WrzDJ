import { afterEach, describe, expect, it, vi } from 'vitest';

describe('authorizeAppleMusic', () => {
  afterEach(() => {
    delete window.MusicKit;
    document.head.replaceChildren();
    vi.resetModules();
  });

  it('configures an already-loaded MusicKit instance and returns its authorization token', async () => {
    const { authorizeAppleMusic } = await import('../apple-music-auth');
    const token = 'music-user-token';
    const authorize = vi.fn().mockResolvedValue(token);
    const configure = vi.fn().mockResolvedValue(undefined);
    window.MusicKit = { configure, getInstance: () => ({ authorize }) };

    await expect(authorizeAppleMusic('developer-token')).resolves.toBe(token);
    expect(configure).toHaveBeenCalledWith({
      developerToken: 'developer-token',
      app: { name: 'WrzDJ', build: '1.0.0' },
    });
    expect(authorize).toHaveBeenCalledOnce();
    expect(document.querySelector('script')).toBeNull();
  });

  it('shares one script load across concurrent authorization requests', async () => {
    const { authorizeAppleMusic } = await import('../apple-music-auth');
    const authorize = vi.fn().mockResolvedValue('music-user-token');
    const configure = vi.fn().mockResolvedValue(undefined);
    const first = authorizeAppleMusic('developer-token');
    const second = authorizeAppleMusic('developer-token');
    const scripts = document.querySelectorAll('script');

    expect(scripts).toHaveLength(1);
    expect(scripts[0].getAttribute('src')).toBe('https://js-cdn.music.apple.com/musickit/v3/musickit.js');

    window.MusicKit = { configure, getInstance: () => ({ authorize }) };
    document.dispatchEvent(new Event('musickitloaded'));

    await expect(Promise.all([first, second])).resolves.toEqual([
      'music-user-token',
      'music-user-token',
    ]);
    expect(configure).toHaveBeenCalledTimes(2);
    expect(authorize).toHaveBeenCalledTimes(2);
  });

  it('allows a fresh script attempt after loading fails', async () => {
    const { authorizeAppleMusic } = await import('../apple-music-auth');
    const first = authorizeAppleMusic('developer-token');
    const firstScript = document.querySelector('script');
    expect(firstScript).not.toBeNull();
    firstScript?.dispatchEvent(new Event('error'));
    await expect(first).rejects.toThrow('Could not load Apple Music authorization.');

    const retry = authorizeAppleMusic('developer-token');
    const scripts = document.querySelectorAll('script');
    expect(scripts).toHaveLength(2);

    const authorize = vi.fn().mockResolvedValue('retry-token');
    window.MusicKit = {
      configure: vi.fn().mockResolvedValue(undefined),
      getInstance: () => ({ authorize }),
    };
    document.dispatchEvent(new Event('musickitloaded'));
    await expect(retry).resolves.toBe('retry-token');
  });
});
