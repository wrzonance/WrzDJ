import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadTurnstileScript } from '../turnstile';

const SCRIPT_URL = 'https://challenges.cloudflare.com/turnstile/v0/api.js';

describe('loadTurnstileScript', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    document.head.innerHTML = '';
    delete window.turnstile;
  });

  afterEach(() => {
    vi.useRealTimers();
    document.head.innerHTML = '';
    delete window.turnstile;
  });

  // Regression for baseline 57cfcdc6867f: a missed script event must settle and allow retry.
  it('times out a script whose error event fired before listeners were attached and permits retry', async () => {
    const staleScript = document.createElement('script');
    staleScript.src = SCRIPT_URL;
    document.head.appendChild(staleScript);
    staleScript.dispatchEvent(new Event('error'));

    const staleLoad = loadTurnstileScript();
    const rejection = expect(staleLoad).rejects.toThrow(/failed to load/);
    await vi.advanceTimersByTimeAsync(15_000);
    await rejection;

    expect(staleScript.isConnected).toBe(false);
    const retry = loadTurnstileScript();
    const retryScript = document.querySelector(`script[src^="${SCRIPT_URL}"]`);
    expect(retryScript).not.toBeNull();
    Object.assign(window, { turnstile: { render: vi.fn() } });
    retryScript?.dispatchEvent(new Event('load'));
    await expect(retry).resolves.toBeUndefined();
  });
});
