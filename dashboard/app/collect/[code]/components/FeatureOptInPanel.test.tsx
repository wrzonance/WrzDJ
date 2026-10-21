import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import FeatureOptInPanel from './FeatureOptInPanel';

// EmailVerification makes real API calls — mock it out for panel tests
vi.mock('../../../../components/EmailVerification', () => ({
  default: ({ isVerified }: { isVerified: boolean }) =>
    isVerified ? <div>Email verified</div> : <div data-testid="email-verification-stub" />,
}));

describe('FeatureOptInPanel', () => {
  it('does not render when guest already has verified email AND a nickname', () => {
    render(
      <FeatureOptInPanel
        emailVerified={true}
        initialNickname="Alex"
        onSave={vi.fn()}
        onVerified={vi.fn()}
      />,
    );
    expect(screen.queryByText(/make it yours/i)).not.toBeInTheDocument();
  });

  it('shows feature copy and nickname input when nothing set yet', () => {
    render(
      <FeatureOptInPanel
        emailVerified={false}
        initialNickname={null}
        onSave={vi.fn()}
        onVerified={vi.fn()}
      />,
    );
    expect(screen.getByText(/nickname appears/i)).toBeInTheDocument();
    expect(screen.getByText(/notify me when my song plays/i)).toBeInTheDocument();
    expect(screen.getByText(/cross-device/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^nickname$/i)).toBeInTheDocument();
  });

  it('requires at least a nickname to save', async () => {
    const onSave = vi.fn();
    render(
      <FeatureOptInPanel
        emailVerified={false}
        initialNickname={null}
        onSave={onSave}
        onVerified={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => {
      expect(screen.getByText(/enter a nickname/i)).toBeInTheDocument();
    });
    expect(onSave).not.toHaveBeenCalled();
  });

  it('calls onSave with nickname when nickname entered', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <FeatureOptInPanel
        emailVerified={false}
        initialNickname={null}
        onSave={onSave}
        onVerified={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText(/^nickname$/i), {
      target: { value: 'DancingQueen' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith({ nickname: 'DancingQueen' });
    });
  });

  it('renders EmailVerification component inside the panel', () => {
    render(
      <FeatureOptInPanel
        emailVerified={false}
        initialNickname={null}
        onSave={vi.fn()}
        onVerified={vi.fn()}
      />,
    );
    expect(screen.getByTestId('email-verification-stub')).toBeInTheDocument();
  });

  // Regression for baseline 57cfcdc6867f: a rejected save value without `.message` rendered no useful error.
  it('shows a useful fallback when saving rejects with a non-Error value', async () => {
    const onSave = vi.fn().mockRejectedValue('offline');
    render(
      <FeatureOptInPanel
        emailVerified={false}
        initialNickname={null}
        onSave={onSave}
        onVerified={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText(/^nickname$/i), { target: { value: 'DancingQueen' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not save your preferences. Please try again.',
    );
  });
});
