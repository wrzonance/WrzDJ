import { afterEach, beforeEach, vi } from 'vitest';
import { api } from '..';

export const mockFetch = vi.fn();

export function setupApiClient() {
  beforeEach(() => {
    vi.stubGlobal('fetch', mockFetch);
    mockFetch.mockReset();
    api.setUnauthorizedHandler(null);
  });

  afterEach(() => {
    api.setUnauthorizedHandler(null);
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });
}
