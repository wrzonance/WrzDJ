import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('../../lib/api', () => ({
  apiClient: {
    requestVerificationCode: vi.fn(),
    confirmVerificationCode: vi.fn(),
  },
  ApiError: class extends Error { status = 0; },
}));

vi.mock('../../lib/turnstile', () => ({
  getTurnstileSiteKey: vi.fn().mockResolvedValue(''),
  loadTurnstileScript: vi.fn().mockResolvedValue(undefined),
}));

import { IdentityBar } from '../IdentityBar';
import { apiClient } from '../../lib/api';

describe('IdentityBar', () => {
  it('shows nickname', () => {
    render(<IdentityBar nickname="DJ_Foo" emailVerified={false} onVerified={vi.fn()} />);
    expect(screen.getByText(/DJ_Foo/)).toBeInTheDocument();
  });

  it('shows pulse element and "Add email" button when email not verified', () => {
    const { container } = render(
      <IdentityBar nickname="DJ_Foo" emailVerified={false} onVerified={vi.fn()} />
    );
    expect(screen.getByRole('button', { name: /add email/i })).toBeInTheDocument();
    expect(container.querySelector('.identity-bar-pulse')).not.toBeNull();
  });

  it('shows verified badge and no Add-email button when email is verified', () => {
    render(<IdentityBar nickname="DJ_Foo" emailVerified={true} onVerified={vi.fn()} />);
    expect(screen.getByText(/verified/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /add email/i })).toBeNull();
  });

  it('clicking "Add email" expands EmailVerification inline', () => {
    render(<IdentityBar nickname="DJ_Foo" emailVerified={false} onVerified={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /add email/i }));
    // EmailVerification in input state renders an email text input
    expect(screen.getByRole('textbox')).toBeInTheDocument();
  });

  it('collapses email form when Skip is clicked', () => {
    render(<IdentityBar nickname="DJ_Foo" emailVerified={false} onVerified={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /add email/i }));
    expect(screen.getByRole('textbox')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /skip for now/i }));
    // After skip, form collapses — email textbox gone, Add email button back
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.getByRole('button', { name: /add email/i })).toBeInTheDocument();
  });

  it('calls onVerified prop when email verification succeeds', async () => {
    const onVerified = vi.fn();
    // Mock the full OTP flow
    (apiClient as any).requestVerificationCode = vi.fn().mockResolvedValue({ sent: true });
    (apiClient as any).confirmVerificationCode = vi.fn().mockResolvedValue({
      verified: true, guest_id: 1, merged: false,
    });

    render(<IdentityBar nickname="DJ_Foo" emailVerified={false} onVerified={onVerified} />);

    // Open email form
    fireEvent.click(screen.getByRole('button', { name: /add email/i }));

    // Enter email and wait for dev-bypass token before clicking send code
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'dj@example.com' } });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /send code/i })).not.toBeDisabled()
    );
    fireEvent.click(screen.getByRole('button', { name: /send code/i }));

    // Fill 6 OTP digits — EmailVerification auto-submits when all filled
    await waitFor(() => screen.getAllByRole('textbox'));
    const inputs = screen.getAllByRole('textbox');
    '123456'.split('').forEach((d, i) => {
      fireEvent.change(inputs[i], { target: { value: d } });
    });

    await waitFor(() => {
      expect(onVerified).toHaveBeenCalledTimes(1);
    });
  });

  it('applies no CSS var overrides by default', () => {
    const { container } = render(
      <IdentityBar nickname="DJ" emailVerified={false} onVerified={vi.fn()} />,
    );
    const root = container.firstChild as HTMLElement;
    expect(root.style.getPropertyValue('--card')).toBe('');
    expect(root.style.getPropertyValue('--text-secondary')).toBe('');
  });

  it('overrides CSS vars when forceDark=true', () => {
    const { container } = render(
      <IdentityBar nickname="DJ" emailVerified={false} onVerified={vi.fn()} forceDark />,
    );
    const root = container.firstChild as HTMLElement;
    expect(root.style.getPropertyValue('--card')).toBe('#1a1a1a');
    expect(root.style.getPropertyValue('--border-subtle')).toBe('rgba(255,255,255,0.08)');
    expect(root.style.getPropertyValue('--text-secondary')).toBe('#9ca3af');
  });

  it('forceDark=false behaves same as omitted', () => {
    const { container } = render(
      <IdentityBar nickname="DJ" emailVerified={false} onVerified={vi.fn()} forceDark={false} />,
    );
    const root = container.firstChild as HTMLElement;
    expect(root.style.getPropertyValue('--card')).toBe('');
  });
});

describe('IdentityBar rename', () => {
  it('shows "Add a name" when autoNamed and calls onRename', async () => {
    const onRename = vi.fn().mockResolvedValue(undefined);
    render(
      <IdentityBar nickname="DancingPanda" emailVerified={false} onVerified={() => {}}
        autoNamed onRename={onRename} />
    );
    fireEvent.click(screen.getByText(/Add a name/i));
    fireEvent.change(screen.getByPlaceholderText(/your name/i), { target: { value: 'Alex' } });
    fireEvent.click(screen.getByText(/^Save$/));
    await waitFor(() => expect(onRename).toHaveBeenCalledWith('Alex'));
  });

  it('does not show "Add a name" when not autoNamed', () => {
    render(<IdentityBar nickname="Alex" emailVerified={false} onVerified={() => {}} />);
    expect(screen.queryByText(/Add a name/i)).not.toBeInTheDocument();
  });
});
