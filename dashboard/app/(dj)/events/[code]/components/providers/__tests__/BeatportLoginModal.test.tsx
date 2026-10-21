import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { BeatportLoginModal } from '../BeatportLoginModal';

describe('BeatportLoginModal', () => {
  it('requires both credentials and submits their original entered values', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<BeatportLoginModal onSubmit={onSubmit} onCancel={vi.fn()} />);
    const connect = screen.getByRole('button', { name: 'Connect' });
    const username = screen.getByLabelText('Username or Email');
    const password = screen.getByLabelText('Password');

    expect(connect).toBeDisabled();
    fireEvent.change(username, { target: { value: '   ' } });
    fireEvent.change(password, { target: { value: 'password' } });
    expect(connect).toBeDisabled();

    fireEvent.change(username, { target: { value: 'dj@example.test' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Connect' }).closest('form')!);

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('dj@example.test', 'password'));
  });

  it('shows a rejected login error and allows another attempt', async () => {
    const onSubmit = vi.fn().mockRejectedValueOnce(new Error('Credentials rejected'));
    render(<BeatportLoginModal onSubmit={onSubmit} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Username or Email'), { target: { value: 'dj' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'bad-pass' } });
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));

    expect(await screen.findByText('Credentials rejected')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Connect' })).toBeEnabled();
  });

  it('prevents canceling while the credential submission is pending', async () => {
    let finishSubmit!: () => void;
    const onSubmit = vi.fn(() => new Promise<void>((resolve) => { finishSubmit = resolve; }));
    const onCancel = vi.fn();
    const { container } = render(<BeatportLoginModal onSubmit={onSubmit} onCancel={onCancel} />);
    fireEvent.change(screen.getByLabelText('Username or Email'), { target: { value: 'dj' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'secret' } });
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));

    expect(screen.getByRole('button', { name: 'Connecting...' })).toBeDisabled();
    fireEvent.click(container.querySelector('.modal-overlay')!);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).not.toHaveBeenCalled();

    finishSubmit();
    await waitFor(() => expect(onSubmit).toHaveBeenCalledOnce());
  });
});
