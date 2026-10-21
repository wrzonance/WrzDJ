import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DeleteEventModal } from '../DeleteEventModal';

describe('DeleteEventModal', () => {
  it('shows the destructive scope and delegates confirmation or cancellation', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <DeleteEventModal
        eventName="Birthday Bash"
        requestCount={17}
        deleting={false}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    expect(screen.getByText(/permanently delete "Birthday Bash" and all 17 song requests/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Delete Event' }));
    expect(onConfirm).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it('locks both actions and backdrop dismissal while deletion is in progress', () => {
    const onCancel = vi.fn();
    const { container } = render(
      <DeleteEventModal
        eventName="Birthday Bash"
        requestCount={0}
        deleting
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );

    expect(screen.getByRole('button', { name: 'Deleting...' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
    fireEvent.click(container.querySelector('.modal-overlay')!);
    expect(onCancel).not.toHaveBeenCalled();
  });
});
