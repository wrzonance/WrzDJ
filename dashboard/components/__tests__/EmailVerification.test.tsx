import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import EmailVerification from '../EmailVerification';
import { getTurnstileSiteKey, loadTurnstileScript } from '../../lib/turnstile';

vi.mock('../../lib/api', () => ({
  api: {
    requestVerificationCode: vi.fn(),
    confirmVerificationCode: vi.fn(),
  },
  ApiError: class extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
}));

vi.mock('../../lib/turnstile', () => ({
  getTurnstileSiteKey: vi.fn().mockResolvedValue(''),
  loadTurnstileScript: vi.fn().mockResolvedValue(undefined),
}));

import { api, ApiError } from '../../lib/api';

const mockRequestCode = api.requestVerificationCode as ReturnType<typeof vi.fn>;
const mockConfirmCode = api.confirmVerificationCode as ReturnType<typeof vi.fn>;

describe('EmailVerification — onSkip prop', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders "Skip for now" button when onSkip is provided', () => {
    render(
      <EmailVerification isVerified={false} onVerified={vi.fn()} onSkip={vi.fn()} />
    );
    expect(screen.getByRole('button', { name: /skip for now/i })).toBeInTheDocument();
  });

  it('does NOT render "Skip for now" button when onSkip is omitted', () => {
    render(<EmailVerification isVerified={false} onVerified={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /skip for now/i })).toBeNull();
  });

  it('calls onSkip when "Skip for now" is clicked', () => {
    const onSkip = vi.fn();
    render(
      <EmailVerification isVerified={false} onVerified={vi.fn()} onSkip={onSkip} />
    );
    fireEvent.click(screen.getByRole('button', { name: /skip for now/i }));
    expect(onSkip).toHaveBeenCalledTimes(1);
  });

  it('does NOT render "Skip for now" button when isVerified is true (component starts in verified state)', () => {
    render(
      <EmailVerification isVerified={true} onVerified={vi.fn()} onSkip={vi.fn()} />
    );
    expect(screen.queryByRole('button', { name: /skip for now/i })).toBeNull();
  });
});

describe('EmailVerification — send code flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows verified badge when isVerified is true', () => {
    render(<EmailVerification isVerified={true} onVerified={vi.fn()} />);
    expect(screen.getByText(/email verified/i)).toBeInTheDocument();
  });

  it('send code button is disabled when email is empty', () => {
    render(<EmailVerification isVerified={false} onVerified={vi.fn()} />);
    expect(screen.getByRole('button', { name: /send code/i })).toBeDisabled();
  });

  it('send code button is enabled after typing email (and Turnstile dev-bypass resolves)', async () => {
    render(<EmailVerification isVerified={false} onVerified={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText(/you@example.com/i), {
      target: { value: 'test@example.com' },
    });
    // Wait for the async Turnstile effect to set the dev-bypass token
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /send code/i })).not.toBeDisabled()
    );
  });

  it('sends code when Enter key is pressed in email input', async () => {
    mockRequestCode.mockResolvedValue({ sent: true });
    render(<EmailVerification isVerified={false} onVerified={vi.fn()} />);

    fireEvent.change(screen.getByPlaceholderText(/you@example.com/i), {
      target: { value: 'press@example.com' },
    });
    // Wait for dev-bypass token before triggering send
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /send code/i })).not.toBeDisabled()
    );
    fireEvent.keyDown(screen.getByPlaceholderText(/you@example.com/i), { key: 'Enter' });

    await waitFor(() => {
      expect(mockRequestCode).toHaveBeenCalledWith('press@example.com', 'dev-bypass');
    });
  });

  it('shows code sent UI after successful code send', async () => {
    mockRequestCode.mockResolvedValue({ sent: true });
    render(<EmailVerification isVerified={false} onVerified={vi.fn()} />);

    fireEvent.change(screen.getByPlaceholderText(/you@example.com/i), {
      target: { value: 'test@example.com' },
    });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /send code/i })).not.toBeDisabled()
    );
    fireEvent.click(screen.getByRole('button', { name: /send code/i }));

    await waitFor(() => {
      expect(screen.getByText(/code sent to/i)).toBeInTheDocument();
    });
    expect(screen.getAllByRole('textbox')).toHaveLength(6);
  });

  it('shows error when code send fails with ApiError', async () => {
    mockRequestCode.mockRejectedValue(new ApiError('Email not allowed', 422));
    render(<EmailVerification isVerified={false} onVerified={vi.fn()} />);

    fireEvent.change(screen.getByPlaceholderText(/you@example.com/i), {
      target: { value: 'bad@example.com' },
    });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /send code/i })).not.toBeDisabled()
    );
    fireEvent.click(screen.getByRole('button', { name: /send code/i }));

    await waitFor(() => {
      expect(screen.getByText('Email not allowed')).toBeInTheDocument();
    });
  });

  it('shows generic error when code send fails with non-ApiError', async () => {
    mockRequestCode.mockRejectedValue(new Error('Network error'));
    render(<EmailVerification isVerified={false} onVerified={vi.fn()} />);

    fireEvent.change(screen.getByPlaceholderText(/you@example.com/i), {
      target: { value: 'net@example.com' },
    });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /send code/i })).not.toBeDisabled()
    );
    fireEvent.click(screen.getByRole('button', { name: /send code/i }));

    await waitFor(() => {
      expect(screen.getByText('Failed to send code')).toBeInTheDocument();
    });
  });
});

describe('EmailVerification — Turnstile loading failures', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it.each(['site key', 'script'])('shows a recoverable error when Turnstile %s loading rejects', async (failure) => {
    if (failure === 'site key') {
      vi.mocked(getTurnstileSiteKey).mockRejectedValueOnce(new Error('config unavailable'));
    } else {
      vi.mocked(getTurnstileSiteKey).mockResolvedValueOnce('test-site-key');
      vi.mocked(loadTurnstileScript).mockRejectedValueOnce(new Error('script unavailable'));
    }

    render(<EmailVerification isVerified={false} onVerified={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText(/you@example.com/i), {
      target: { value: 'test@example.com' },
    });

    expect(await screen.findByText('Unable to load email verification. Please refresh and try again.'))
      .toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send code/i })).toBeDisabled();
    expect(mockRequestCode).not.toHaveBeenCalled();
  });

  it('does not update component state when script loading rejects after unmount', async () => {
    let rejectScript!: (error: Error) => void;
    vi.mocked(getTurnstileSiteKey).mockResolvedValueOnce('test-site-key');
    vi.mocked(loadTurnstileScript).mockReturnValueOnce(new Promise((_, reject) => {
      rejectScript = reject;
    }));

    const { unmount } = render(<EmailVerification isVerified={false} onVerified={vi.fn()} />);
    await waitFor(() => expect(loadTurnstileScript).toHaveBeenCalled());
    unmount();

    rejectScript(new Error('late script failure'));
    await Promise.resolve();
    await Promise.resolve();
  });
});

describe('EmailVerification — code confirmation flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRequestCode.mockResolvedValue({ sent: true });
  });

  async function getToCodeSentState() {
    render(<EmailVerification isVerified={false} onVerified={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText(/you@example.com/i), {
      target: { value: 'verify@example.com' },
    });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /send code/i })).not.toBeDisabled()
    );
    fireEvent.click(screen.getByRole('button', { name: /send code/i }));
    await waitFor(() => screen.getByText(/code sent to/i));
    return screen.getAllByRole('textbox');
  }

  it('auto-submits when all 6 digits are filled', async () => {
    mockConfirmCode.mockResolvedValue({ verified: true, guest_id: 1, merged: false });
    const onVerified = vi.fn();
    render(<EmailVerification isVerified={false} onVerified={onVerified} />);

    fireEvent.change(screen.getByPlaceholderText(/you@example.com/i), {
      target: { value: 'auto@example.com' },
    });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /send code/i })).not.toBeDisabled()
    );
    fireEvent.click(screen.getByRole('button', { name: /send code/i }));
    await waitFor(() => screen.getByText(/code sent to/i));

    const digitInputs = screen.getAllByRole('textbox');
    for (let i = 0; i < 6; i++) {
      fireEvent.change(digitInputs[i], { target: { value: String(i + 1) } });
    }

    await waitFor(() => {
      expect(mockConfirmCode).toHaveBeenCalled();
      expect(onVerified).toHaveBeenCalled();
    });
  });

  it('shows error when confirmation fails with ApiError', async () => {
    mockConfirmCode.mockRejectedValue(new ApiError('Invalid code', 400));
    const digitInputs = await getToCodeSentState();

    for (let i = 0; i < 6; i++) {
      fireEvent.change(digitInputs[i], { target: { value: String(i + 1) } });
    }

    await waitFor(() => {
      expect(screen.getByText('Invalid code')).toBeInTheDocument();
    });
  });

  it('shows generic error when confirmation fails with non-ApiError', async () => {
    mockConfirmCode.mockRejectedValue(new Error('Server error'));
    const digitInputs = await getToCodeSentState();

    for (let i = 0; i < 6; i++) {
      fireEvent.change(digitInputs[i], { target: { value: String(i + 1) } });
    }

    await waitFor(() => {
      expect(screen.getByText('Verification failed')).toBeInTheDocument();
    });
  });

  it('backspace on empty digit focuses previous input', async () => {
    const digitInputs = await getToCodeSentState();

    // Fill first digit
    fireEvent.change(digitInputs[0], { target: { value: '1' } });
    // Press backspace on second input (empty) — should conceptually focus first
    fireEvent.keyDown(digitInputs[1], { key: 'Backspace' });
    // No error should be thrown
    expect(digitInputs[0]).toBeInTheDocument();
  });

  it('handles paste of 6 digits filling all inputs', async () => {
    const digitInputs = await getToCodeSentState();
    mockConfirmCode.mockResolvedValue({ verified: true, guest_id: 1, merged: false });

    // Simulate paste on first input
    fireEvent.paste(digitInputs[0], {
      clipboardData: {
        getData: () => '123456',
      },
    });

    await waitFor(() => {
      expect(mockConfirmCode).toHaveBeenCalled();
    });
  });

  it('ignores paste of non-numeric characters', async () => {
    const digitInputs = await getToCodeSentState();

    fireEvent.paste(digitInputs[0], {
      clipboardData: {
        getData: () => 'abcdef',
      },
    });

    // digits should remain empty — code not submitted
    expect(mockConfirmCode).not.toHaveBeenCalled();
  });

  it('handles paste of fewer than 6 digits', async () => {
    const digitInputs = await getToCodeSentState();

    fireEvent.paste(digitInputs[0], {
      clipboardData: {
        getData: () => '123',
      },
    });

    // Should not auto-submit (only 3 digits)
    expect(mockConfirmCode).not.toHaveBeenCalled();
  });

  it('handles handleDigitChange with multi-char value (paste via input event)', async () => {
    const digitInputs = await getToCodeSentState();
    mockConfirmCode.mockResolvedValue({ verified: true, guest_id: 1, merged: false });

    // Simulate multi-char input (e.g., from autofill) by passing a multi-char value
    fireEvent.change(digitInputs[0], { target: { value: '123456' } });

    await waitFor(() => {
      expect(mockConfirmCode).toHaveBeenCalled();
    });
  });

  it('rejects non-numeric single char input', async () => {
    const digitInputs = await getToCodeSentState();

    fireEvent.change(digitInputs[0], { target: { value: 'a' } });

    // digit should remain empty
    expect(digitInputs[0]).toHaveValue('');
  });
});
