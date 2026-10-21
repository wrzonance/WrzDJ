import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import EmailGate from '../EmailGate';

vi.mock('../EmailVerification', () => ({
  default: ({ onVerified }: { onVerified: () => void }) => (
    <button type="button" onClick={onVerified}>Complete verification</button>
  ),
}));

describe('EmailGate', () => {
  it('renders protected children directly after verification', () => {
    render(
      <EmailGate verified onVerified={vi.fn()}>
        <button type="button">Submit a request</button>
      </EmailGate>,
    );

    expect(screen.getByRole('button', { name: 'Submit a request' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Complete verification' })).not.toBeInTheDocument();
  });

  it('blocks interaction behind the verification dialog and forwards completion', () => {
    const onVerified = vi.fn();
    render(
      <EmailGate verified={false} onVerified={onVerified}>
        <button type="button">Submit a request</button>
      </EmailGate>,
    );

    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true');
    expect(screen.getByRole('heading', { name: 'Verify your email to continue' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Complete verification' })).toBeInTheDocument();
    expect(screen.getByText('Submit a request').closest('[aria-hidden="true"]')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Complete verification' }));
    expect(onVerified).toHaveBeenCalledOnce();
  });
});
