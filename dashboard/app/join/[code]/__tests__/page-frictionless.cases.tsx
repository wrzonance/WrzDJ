import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import type { JoinPageTestContext } from './page-test-context';

export function registerFrictionlessTests(context: JoinPageTestContext) {
  const { JoinEventPage, mockApi, MockApiError, MockHumanVerificationRequiredError, nicknameGateRenderSpy, setupDefaultMocks } = context;


describe('JoinEventPage — frictionless join', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
  });

  it('auto-names after a 403-then-verified retry without flashing NicknameGate', async () => {
    mockApi.getJoinConfig.mockResolvedValue({ frictionless_join: true });
    mockApi.getPublicEvent.mockResolvedValue({
      name: 'Party',
      collection_code: 'TEST01',
      requests_open: true,
      frictionless_join: true,
      phase: 'live',
      submission_cap_per_guest: 5,
      banner_url: null,
      banner_colors: null,
    });
    let reverifyAwaited = false;
    mockApi.ensureGuestName.mockImplementation(
      async (_code: string, options?: { reverify?: () => Promise<void> }) => {
        // Simulate withHumanRetry under enforcement: first attempt 403s, the
        // wrapper awaits reverify (resolves once the cookie is set), retries.
        await options?.reverify?.();
        reverifyAwaited = true;
        return { nickname: 'VerifiedOtter', auto_generated: true };
      },
    );

    render(<JoinEventPage />);

    await waitFor(() => expect(screen.getByText(/VerifiedOtter/)).toBeInTheDocument());
    expect(reverifyAwaited).toBe(true);
    // Not just absent from the final DOM — the gate must never have mounted at all.
    expect(nicknameGateRenderSpy).not.toHaveBeenCalled();
    expect(screen.queryByTestId('nickname-gate')).not.toBeInTheDocument();
  });

  it('shows the verification overlay, not NicknameGate, when verification cannot complete', async () => {
    mockApi.getJoinConfig.mockResolvedValue({ frictionless_join: true });
    mockApi.ensureGuestName.mockRejectedValue(new MockHumanVerificationRequiredError());

    render(<JoinEventPage />);

    await waitFor(() =>
      expect(screen.getByText(/Verification didn.t go through/i)).toBeInTheDocument(),
    );
    expect(nicknameGateRenderSpy).not.toHaveBeenCalled();
    expect(screen.queryByTestId('nickname-gate')).not.toBeInTheDocument();
  });

  it('also holds the overlay when reverify rejects with HumanVerificationFailedError', async () => {
    const { HumanVerificationFailedError } = await import('@/lib/use-human-verification');
    mockApi.getJoinConfig.mockResolvedValue({ frictionless_join: true });
    mockApi.ensureGuestName.mockRejectedValue(new HumanVerificationFailedError());

    render(<JoinEventPage />);

    await waitFor(() =>
      expect(screen.getByText(/Verification didn.t go through/i)).toBeInTheDocument(),
    );
    expect(nicknameGateRenderSpy).not.toHaveBeenCalled();
    expect(screen.queryByTestId('nickname-gate')).not.toBeInTheDocument();
  });

  it('still falls back to NicknameGate on non-verification errors (e.g. frictionless_disabled)', async () => {
    mockApi.getJoinConfig.mockResolvedValue({ frictionless_join: true });
    mockApi.ensureGuestName.mockRejectedValue(new MockApiError('frictionless_disabled', 403));

    render(<JoinEventPage />);

    // The NicknameGate mock auto-completes with TestUser — proof the gate path ran.
    await waitFor(() => expect(screen.getByTestId('identity-bar')).toHaveTextContent('TestUser'));
  });

  it('skips NicknameGate and auto-names when frictionless_join is on', async () => {
    mockApi.getJoinConfig.mockResolvedValue({ frictionless_join: true });
    mockApi.ensureGuestName.mockResolvedValue({ nickname: 'DancingPanda', auto_generated: true });
    mockApi.getEvent.mockResolvedValue({
      id: 1, code: 'TEST01', join_code: 'TEST01', name: 'Party', requests_open: true,
      frictionless_join: true,
    } as never);
    mockApi.getPublicEvent.mockResolvedValue({
      name: 'Party',
      collection_code: 'TEST01',
      requests_open: true,
      frictionless_join: true,
      phase: 'live',
      submission_cap_per_guest: 5,
      banner_url: null,
      banner_colors: null,
    });
    mockApi.checkHasRequested.mockResolvedValue({ has_requested: false } as never);
    render(<JoinEventPage />);
    // No "What's your nickname?" gate; the auto-name shows in the identity bar.
    await waitFor(() => expect(screen.getByText(/DancingPanda/)).toBeInTheDocument());
    expect(screen.queryByText(/What's your nickname/i)).not.toBeInTheDocument();
  });
});

describe('JoinEventPage — checkHasRequested failure', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
    mockApi.checkHasRequested.mockRejectedValue(new Error('Network error'));
  });

  it('falls back gracefully when checkHasRequested fails', async () => {
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByText('Test Event')).toBeInTheDocument();
    });
    expect(await screen.findByPlaceholderText(/search for a song/i)).toBeInTheDocument();
  });
});
}
