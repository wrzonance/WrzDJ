import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NicknameGate } from '../NicknameGate';

vi.mock('../../lib/api', () => {
  class ApiError extends Error {
    status: number;
    constructor(msg: string, status: number) {
      super(msg);
      this.name = 'ApiError';
      this.status = status;
    }
  }
  class NicknameConflictError extends Error {
    claimed: boolean;
    constructor(claimed: boolean) {
      super('nickname_taken');
      this.name = 'NicknameConflictError';
      this.claimed = claimed;
    }
  }
  class EmailVerificationRequiredError extends Error {
    constructor() {
      super('email_verification_required');
      this.name = 'EmailVerificationRequiredError';
    }
  }
  return {
    apiClient: {
      getCollectProfile: vi.fn(),
      setCollectProfile: vi.fn(),
      requestVerificationCode: vi.fn(),
      confirmVerificationCode: vi.fn(),
    },
    ApiError,
    NicknameConflictError,
    EmailVerificationRequiredError,
  };
});

vi.mock('../../lib/use-guest-identity', () => ({
  useGuestIdentity: () => ({
    isLoading: false,
    guestId: 1,
    isReturning: false,
    reconcileHint: false,
    refresh: vi.fn(),
  }),
}));

vi.mock('../EmailVerification', () => ({
  default: ({ onVerified, onSkip }: { onVerified: () => void; onSkip: () => void }) => (
    <div>
      <button onClick={onVerified}>Verify Email</button>
      <button onClick={onSkip}>Skip Email</button>
    </div>
  ),
}));

vi.mock('../../lib/turnstile', () => ({
  getTurnstileSiteKey: vi.fn().mockResolvedValue(''),
  loadTurnstileScript: vi.fn().mockResolvedValue(undefined),
}));

import { apiClient, NicknameConflictError } from '../../lib/api';

const mockGetProfile = vi.mocked(apiClient.getCollectProfile);
const mockSetProfile = vi.mocked(apiClient.setCollectProfile);
const mockRequestCode = vi.mocked(apiClient.requestVerificationCode);
const mockConfirmCode = vi.mocked(apiClient.confirmVerificationCode);

const emptyProfile = {
  nickname: null,
  email_verified: false,
  submission_count: 0,
  submission_cap: 5,
};

describe('NicknameGate', () => {
  const onComplete = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockGetProfile.mockResolvedValue(emptyProfile);
    mockSetProfile.mockResolvedValue({ ...emptyProfile, nickname: 'TestUser' });
    mockRequestCode.mockResolvedValue({ sent: true });
    mockConfirmCode.mockResolvedValue({ verified: true, guest_id: 1, merged: false });
  });

  it('renders track_select when no profile exists', async () => {
    render(<NicknameGate code="EVT01" onComplete={onComplete} />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /new name/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /have email/i })).toBeInTheDocument();
    });
  });

  it('transitions to nickname_input when "New name" clicked', async () => {
    render(<NicknameGate code="EVT01" onComplete={onComplete} />);
    await waitFor(() => screen.getByRole('button', { name: /new name/i }));
    fireEvent.click(screen.getByRole('button', { name: /new name/i }));
    expect(screen.getByPlaceholderText(/dancingqueen/i)).toBeInTheDocument();
  });

  it('transitions to email_login when "Have email" clicked', async () => {
    render(<NicknameGate code="EVT01" onComplete={onComplete} />);
    await waitFor(() => screen.getByRole('button', { name: /have email/i }));
    fireEvent.click(screen.getByRole('button', { name: /have email/i }));
    expect(screen.getByPlaceholderText(/you@example\.com/i)).toBeInTheDocument();
  });

  it('shows collision_unclaimed state on 409 claimed=false', async () => {
    mockSetProfile.mockRejectedValue(new NicknameConflictError(false));
    render(<NicknameGate code="EVT01" onComplete={onComplete} />);
    await waitFor(() => screen.getByRole('button', { name: /new name/i }));
    fireEvent.click(screen.getByRole('button', { name: /new name/i }));
    fireEvent.change(screen.getByPlaceholderText(/dancingqueen/i), { target: { value: 'Alex' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => {
      expect(screen.getByText(/already taken/i)).toBeInTheDocument();
      expect(screen.getByText(/original device/i)).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: /log in with email/i })).not.toBeInTheDocument();
  });

  it('shows collision_claimed state on 409 claimed=true', async () => {
    mockSetProfile.mockRejectedValue(new NicknameConflictError(true));
    render(<NicknameGate code="EVT01" onComplete={onComplete} />);
    await waitFor(() => screen.getByRole('button', { name: /new name/i }));
    fireEvent.click(screen.getByRole('button', { name: /new name/i }));
    fireEvent.change(screen.getByPlaceholderText(/dancingqueen/i), { target: { value: 'Alex' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => {
      expect(screen.getByText(/already taken/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /log in with email/i })).toBeInTheDocument();
    });
  });

  it('"Try a different nickname" from collision_unclaimed returns to nickname_input', async () => {
    mockSetProfile.mockRejectedValue(new NicknameConflictError(false));
    render(<NicknameGate code="EVT01" onComplete={onComplete} />);
    await waitFor(() => screen.getByRole('button', { name: /new name/i }));
    fireEvent.click(screen.getByRole('button', { name: /new name/i }));
    fireEvent.change(screen.getByPlaceholderText(/dancingqueen/i), { target: { value: 'Alex' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => screen.getByText(/original device/i));
    fireEvent.click(screen.getByRole('button', { name: /try a different/i }));
    expect(screen.getByPlaceholderText(/dancingqueen/i)).toBeInTheDocument();
  });

  it('"Try a different nickname" from collision_claimed returns to nickname_input', async () => {
    mockSetProfile.mockRejectedValue(new NicknameConflictError(true));
    render(<NicknameGate code="EVT01" onComplete={onComplete} />);
    await waitFor(() => screen.getByRole('button', { name: /new name/i }));
    fireEvent.click(screen.getByRole('button', { name: /new name/i }));
    fireEvent.change(screen.getByPlaceholderText(/dancingqueen/i), { target: { value: 'Alex' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => screen.getByRole('button', { name: /log in with email/i }));
    fireEvent.click(screen.getByRole('button', { name: /try a different/i }));
    expect(screen.getByPlaceholderText(/dancingqueen/i)).toBeInTheDocument();
  });

  // Regression: a brand-new guest in a private tab is not email-verified, so
  // claiming a name (POST /collect/{code}/profile -> require_email_verified)
  // returns 403 email_verification_required. Previously this fell through to a
  // generic "Couldn't save" dead-end; now it must route into the email flow.
  it('routes to email verification (not a dead-end) when a name claim requires email', async () => {
    const { EmailVerificationRequiredError } = await import('../../lib/api');
    mockSetProfile.mockRejectedValueOnce(new EmailVerificationRequiredError());
    render(<NicknameGate code="EVT01" onComplete={onComplete} reverify={vi.fn()} />);
    await waitFor(() => screen.getByRole('button', { name: /new name/i }));
    fireEvent.click(screen.getByRole('button', { name: /new name/i }));
    fireEvent.change(screen.getByPlaceholderText(/dancingqueen/i), { target: { value: 'Alex' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    // Lands on the email-login step…
    await waitFor(() =>
      expect(screen.getByPlaceholderText(/you@example\.com/i)).toBeInTheDocument(),
    );
    // …and NOT the old generic dead-end error.
    expect(screen.queryByText(/couldn.t save/i)).not.toBeInTheDocument();
  });

  it('auto-claims the chosen name after email verification', async () => {
    const { EmailVerificationRequiredError } = await import('../../lib/api');
    // 1st save is blocked by the email gate; 2nd save (post-verify) succeeds.
    mockSetProfile
      .mockRejectedValueOnce(new EmailVerificationRequiredError())
      .mockResolvedValueOnce({
        nickname: 'Alex',
        email_verified: true,
        submission_count: 0,
        submission_cap: 5,
      });
    // Profile after code-confirm still has no nickname (the blocked save never persisted).
    mockGetProfile
      .mockResolvedValueOnce(emptyProfile)
      .mockResolvedValueOnce({
        nickname: null,
        email_verified: true,
        submission_count: 0,
        submission_cap: 5,
      });
    render(<NicknameGate code="EVT01" onComplete={onComplete} reverify={vi.fn()} />);
    await waitFor(() => screen.getByRole('button', { name: /new name/i }));
    fireEvent.click(screen.getByRole('button', { name: /new name/i }));
    fireEvent.change(screen.getByPlaceholderText(/dancingqueen/i), { target: { value: 'Alex' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => screen.getByPlaceholderText(/you@example\.com/i));
    fireEvent.change(screen.getByPlaceholderText(/you@example\.com/i), {
      target: { value: 'alex@example.com' },
    });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /send code/i })).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: /send code/i }));
    await waitFor(() => screen.getByPlaceholderText(/6.digit/i));
    fireEvent.change(screen.getByPlaceholderText(/6.digit/i), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: /^verify$/i }));
    await waitFor(() =>
      expect(onComplete).toHaveBeenCalledWith(
        expect.objectContaining({ nickname: 'Alex', emailVerified: true }),
      ),
    );
    // The name was claimed in a second profile write, after email was verified.
    expect(mockSetProfile).toHaveBeenCalledTimes(2);
  });

  it('shows the collision state if the chosen name is taken during email verification', async () => {
    const { EmailVerificationRequiredError, NicknameConflictError } = await import('../../lib/api');
    mockSetProfile
      .mockRejectedValueOnce(new EmailVerificationRequiredError())
      .mockRejectedValueOnce(new NicknameConflictError(false));
    mockGetProfile
      .mockResolvedValueOnce(emptyProfile)
      .mockResolvedValueOnce({
        nickname: null,
        email_verified: true,
        submission_count: 0,
        submission_cap: 5,
      });
    render(<NicknameGate code="EVT01" onComplete={onComplete} reverify={vi.fn()} />);
    await waitFor(() => screen.getByRole('button', { name: /new name/i }));
    fireEvent.click(screen.getByRole('button', { name: /new name/i }));
    fireEvent.change(screen.getByPlaceholderText(/dancingqueen/i), { target: { value: 'Alex' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => screen.getByPlaceholderText(/you@example\.com/i));
    fireEvent.change(screen.getByPlaceholderText(/you@example\.com/i), {
      target: { value: 'alex@example.com' },
    });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /send code/i })).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: /send code/i }));
    await waitFor(() => screen.getByPlaceholderText(/6.digit/i));
    fireEvent.change(screen.getByPlaceholderText(/6.digit/i), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: /^verify$/i }));
    await waitFor(() => expect(screen.getByText(/already taken/i)).toBeInTheDocument());
    expect(onComplete).not.toHaveBeenCalled();
  });

  it('clears the deferred name when the email-required flow is abandoned via Back', async () => {
    const { EmailVerificationRequiredError } = await import('../../lib/api');
    mockSetProfile.mockRejectedValueOnce(new EmailVerificationRequiredError());
    mockGetProfile
      .mockResolvedValueOnce(emptyProfile)
      .mockResolvedValueOnce({
        nickname: null,
        email_verified: true,
        submission_count: 0,
        submission_cap: 5,
      });
    render(<NicknameGate code="EVT01" onComplete={onComplete} reverify={vi.fn()} />);
    await waitFor(() => screen.getByRole('button', { name: /new name/i }));
    fireEvent.click(screen.getByRole('button', { name: /new name/i }));
    fireEvent.change(screen.getByPlaceholderText(/dancingqueen/i), { target: { value: 'Alex' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    // Blocked → routed to the email step; the user backs out…
    await waitFor(() => screen.getByPlaceholderText(/you@example\.com/i));
    fireEvent.click(screen.getByRole('button', { name: /back/i }));
    // …then chooses the normal email-login path instead.
    await waitFor(() => screen.getByRole('button', { name: /have email/i }));
    fireEvent.click(screen.getByRole('button', { name: /have email/i }));
    fireEvent.change(screen.getByPlaceholderText(/you@example\.com/i), {
      target: { value: 'someone@example.com' },
    });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /send code/i })).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: /send code/i }));
    await waitFor(() => screen.getByPlaceholderText(/6.digit/i));
    fireEvent.change(screen.getByPlaceholderText(/6.digit/i), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: /^verify$/i }));
    // The abandoned 'Alex' must NOT be auto-claimed; lands on a fresh name prompt.
    await waitFor(() => expect(screen.getByPlaceholderText(/dancingqueen/i)).toBeInTheDocument());
    expect(mockSetProfile).toHaveBeenCalledTimes(1);
    expect(onComplete).not.toHaveBeenCalled();
  });

  it('keeps the verified state and unblocks if the deferred claim fails after OTP', async () => {
    const { EmailVerificationRequiredError, ApiError } = await import('../../lib/api');
    mockSetProfile
      .mockRejectedValueOnce(new EmailVerificationRequiredError())
      .mockRejectedValueOnce(new ApiError('server error', 500));
    mockGetProfile
      .mockResolvedValueOnce(emptyProfile)
      .mockResolvedValueOnce({
        nickname: null,
        email_verified: true,
        submission_count: 0,
        submission_cap: 5,
      });
    render(<NicknameGate code="EVT01" onComplete={onComplete} reverify={vi.fn()} />);
    await waitFor(() => screen.getByRole('button', { name: /new name/i }));
    fireEvent.click(screen.getByRole('button', { name: /new name/i }));
    fireEvent.change(screen.getByPlaceholderText(/dancingqueen/i), { target: { value: 'Alex' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => screen.getByPlaceholderText(/you@example\.com/i));
    fireEvent.change(screen.getByPlaceholderText(/you@example\.com/i), {
      target: { value: 'alex@example.com' },
    });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /send code/i })).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: /send code/i }));
    await waitFor(() => screen.getByPlaceholderText(/6.digit/i));
    fireEvent.change(screen.getByPlaceholderText(/6.digit/i), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: /^verify$/i }));
    // OTP consumed + email verified, but the claim failed: move OFF the code
    // screen to the name prompt rather than stranding the user behind a used code.
    await waitFor(() => expect(screen.getByPlaceholderText(/dancingqueen/i)).toBeInTheDocument());
    expect(screen.queryByPlaceholderText(/6.digit/i)).not.toBeInTheDocument();
    expect(onComplete).not.toHaveBeenCalled();
  });

  it('transitions to complete when email verified and profile has nickname', async () => {
    mockGetProfile
      .mockResolvedValueOnce(emptyProfile)
      .mockResolvedValueOnce({
        nickname: 'Alex',
        email_verified: true,
        submission_count: 0,
        submission_cap: 5,
      });
    render(<NicknameGate code="EVT01" onComplete={onComplete} />);
    await waitFor(() => screen.getByRole('button', { name: /have email/i }));
    fireEvent.click(screen.getByRole('button', { name: /have email/i }));
    fireEvent.change(screen.getByPlaceholderText(/you@example\.com/i), {
      target: { value: 'test@example.com' },
    });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /send code/i })).not.toBeDisabled()
    );
    fireEvent.click(screen.getByRole('button', { name: /send code/i }));
    await waitFor(() => screen.getByPlaceholderText(/6.digit/i));
    fireEvent.change(screen.getByPlaceholderText(/6.digit/i), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: /^verify$/i }));
    await waitFor(() =>
      expect(onComplete).toHaveBeenCalledWith(
        expect.objectContaining({ nickname: 'Alex', emailVerified: true }),
      ),
    );
  });

  it('transitions to nickname_input when email verified but no nickname on guest', async () => {
    mockGetProfile
      .mockResolvedValueOnce(emptyProfile)
      .mockResolvedValueOnce({
        nickname: null,
        email_verified: true,
        submission_count: 0,
        submission_cap: 5,
      });
    render(<NicknameGate code="EVT01" onComplete={onComplete} />);
    await waitFor(() => screen.getByRole('button', { name: /have email/i }));
    fireEvent.click(screen.getByRole('button', { name: /have email/i }));
    fireEvent.change(screen.getByPlaceholderText(/you@example\.com/i), {
      target: { value: 'test@example.com' },
    });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /send code/i })).not.toBeDisabled()
    );
    fireEvent.click(screen.getByRole('button', { name: /send code/i }));
    await waitFor(() => screen.getByPlaceholderText(/6.digit/i));
    fireEvent.change(screen.getByPlaceholderText(/6.digit/i), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: /^verify$/i }));
    await waitFor(() => expect(screen.getByPlaceholderText(/dancingqueen/i)).toBeInTheDocument());
  });

  it('skips email_prompt when nickname saved while already email-verified', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mockGetProfile
        .mockResolvedValueOnce(emptyProfile)
        .mockResolvedValueOnce({
          nickname: null,
          email_verified: true,
          submission_count: 0,
          submission_cap: 5,
        });
      mockSetProfile.mockResolvedValue({
        nickname: 'NewUser',
        email_verified: true,
        submission_count: 0,
        submission_cap: 5,
      });
      render(<NicknameGate code="EVT01" onComplete={onComplete} />);
      await waitFor(() => screen.getByRole('button', { name: /have email/i }));
      fireEvent.click(screen.getByRole('button', { name: /have email/i }));
      fireEvent.change(screen.getByPlaceholderText(/you@example\.com/i), {
        target: { value: 'test@example.com' },
      });
      await waitFor(() =>
        expect(screen.getByRole('button', { name: /send code/i })).not.toBeDisabled()
      );
      fireEvent.click(screen.getByRole('button', { name: /send code/i }));
      await waitFor(() => screen.getByPlaceholderText(/6.digit/i));
      fireEvent.change(screen.getByPlaceholderText(/6.digit/i), { target: { value: '123456' } });
      fireEvent.click(screen.getByRole('button', { name: /^verify$/i }));
      await waitFor(() => screen.getByPlaceholderText(/dancingqueen/i));
      fireEvent.change(screen.getByPlaceholderText(/dancingqueen/i), {
        target: { value: 'NewUser' },
      });
      fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
      // Wait for setCollectProfile to resolve, then advance fake timers past the 1500ms savedFlash delay
      await act(async () => {
        await Promise.resolve(); // let the mock promise resolve
        vi.runAllTimers();
      });
      await waitFor(() =>
        expect(onComplete).toHaveBeenCalledWith(
          expect.objectContaining({ nickname: 'NewUser', emailVerified: true }),
        ),
      );
      expect(screen.queryByText(/add your email/i)).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('NicknameGate — existing behavior coverage', () => {
  const onComplete = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockGetProfile.mockResolvedValue(emptyProfile);
    mockSetProfile.mockResolvedValue({ ...emptyProfile, nickname: 'TestUser' });
    mockRequestCode.mockResolvedValue({ sent: true });
    mockConfirmCode.mockResolvedValue({ verified: true, guest_id: 1, merged: false });
  });

  it('calls onComplete immediately when profile has nickname + email verified', async () => {
    mockGetProfile.mockResolvedValue({
      nickname: 'Alex',
      email_verified: true,
      submission_count: 2,
      submission_cap: 5,
    });
    render(<NicknameGate code="EVT01" onComplete={onComplete} />);
    await waitFor(() =>
      expect(onComplete).toHaveBeenCalledWith({
        nickname: 'Alex',
        emailVerified: true,
        submissionCount: 2,
        submissionCap: 5,
      }),
    );
  });

  it('shows email_prompt when profile has nickname but no email', async () => {
    mockGetProfile.mockResolvedValue({
      nickname: 'Alex',
      email_verified: false,
      submission_count: 0,
      submission_cap: 5,
    });
    render(<NicknameGate code="EVT01" onComplete={onComplete} />);
    await waitFor(() => expect(screen.getByText(/add your email/i)).toBeInTheDocument());
  });

  it('calls onComplete on 404 with empty nickname', async () => {
    const { ApiError } = await import('../../lib/api');
    mockGetProfile.mockRejectedValue(new ApiError('not found', 404));
    render(<NicknameGate code="EVT01" onComplete={onComplete} />);
    await waitFor(() =>
      expect(onComplete).toHaveBeenCalledWith({
        nickname: '',
        emailVerified: false,
        submissionCount: 0,
        submissionCap: 0,
      }),
    );
  });

  it('shows error state on network failure with Retry button', async () => {
    mockGetProfile.mockRejectedValue(new Error('network error'));
    render(<NicknameGate code="EVT01" onComplete={onComplete} />);
    await waitFor(() => expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument());
  });

  it('Save button is disabled when nickname input is empty', async () => {
    render(<NicknameGate code="EVT01" onComplete={onComplete} />);
    await waitFor(() => screen.getByRole('button', { name: /new name/i }));
    fireEvent.click(screen.getByRole('button', { name: /new name/i }));
    const saveBtn = screen.getByRole('button', { name: /^save$/i });
    expect(saveBtn).toBeDisabled();
  });

  it('shows validation error for nickname that is too short', async () => {
    render(<NicknameGate code="EVT01" onComplete={onComplete} />);
    await waitFor(() => screen.getByRole('button', { name: /new name/i }));
    fireEvent.click(screen.getByRole('button', { name: /new name/i }));
    fireEvent.change(screen.getByPlaceholderText(/dancingqueen/i), { target: { value: 'x' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    expect(screen.getByText(/at least 2 characters/i)).toBeInTheDocument();
    expect(mockSetProfile).not.toHaveBeenCalled();
  });

  it('shows inline error when setCollectProfile fails with generic error', async () => {
    const { ApiError } = await import('../../lib/api');
    mockSetProfile.mockRejectedValue(new ApiError('server error', 500));
    render(<NicknameGate code="EVT01" onComplete={onComplete} />);
    await waitFor(() => screen.getByRole('button', { name: /new name/i }));
    fireEvent.click(screen.getByRole('button', { name: /new name/i }));
    fireEvent.change(screen.getByPlaceholderText(/dancingqueen/i), { target: { value: 'Alex' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(screen.getByText(/server error/i)).toBeInTheDocument());
  });

  it('skip from email_prompt calls onComplete with emailVerified=false', async () => {
    mockGetProfile.mockResolvedValue({
      nickname: 'Alex',
      email_verified: false,
      submission_count: 1,
      submission_cap: 5,
    });
    render(<NicknameGate code="EVT01" onComplete={onComplete} />);
    await waitFor(() => screen.getByText(/add your email/i));
    fireEvent.click(screen.getByRole('button', { name: /skip email/i }));
    expect(onComplete).toHaveBeenCalledWith(
      expect.objectContaining({ nickname: 'Alex', emailVerified: false }),
    );
  });

  it('verify from email_prompt calls onComplete with emailVerified=true', async () => {
    mockGetProfile.mockResolvedValue({
      nickname: 'Alex',
      email_verified: false,
      submission_count: 1,
      submission_cap: 5,
    });
    render(<NicknameGate code="EVT01" onComplete={onComplete} />);
    await waitFor(() => screen.getByText(/add your email/i));
    fireEvent.click(screen.getByRole('button', { name: /verify email/i }));
    expect(onComplete).toHaveBeenCalledWith(
      expect.objectContaining({ nickname: 'Alex', emailVerified: true }),
    );
  });
});
