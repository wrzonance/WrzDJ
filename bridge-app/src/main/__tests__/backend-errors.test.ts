import { describe, expect, it, vi } from 'vitest';
import { readBackendErrorDetail } from '../backend-errors.js';

describe('readBackendErrorDetail', () => {
  it('uses the fallback for malformed JSON', async () => {
    const response = { json: vi.fn().mockRejectedValue(new SyntaxError('invalid JSON')) } as unknown as Response;

    await expect(readBackendErrorDetail(response, 'Request failed')).resolves.toBe('Request failed');
  });

  it('preserves response body abort failures', async () => {
    const abort = new DOMException('The operation was aborted.', 'AbortError');
    const response = { json: vi.fn().mockRejectedValue(abort) } as unknown as Response;

    await expect(readBackendErrorDetail(response, 'Request failed')).rejects.toBe(abort);
  });

  it('preserves response body read failures without exposing body contents', async () => {
    // Regression coverage for 57cfcdc6867f: preserve transport causes without logging response bodies.
    const failure = new TypeError('terminated');
    const response = { json: vi.fn().mockRejectedValue(failure) } as unknown as Response;

    await expect(readBackendErrorDetail(response, 'Request failed')).rejects.toBe(failure);
  });
});
