import { fireEvent, render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ModalOverlay } from '../ModalOverlay';

describe('ModalOverlay', () => {
  it('dismisses on backdrop click without dismissing when card content is clicked', () => {
    const onClose = vi.fn();
    const { container, getByText } = render(
      <ModalOverlay card onClose={onClose}>
        <button type="button">Continue editing</button>
      </ModalOverlay>,
    );

    fireEvent.click(getByText('Continue editing'));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(container.querySelector('.modal-overlay')!);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('keeps the backdrop active without invoking dismissal when onClose is disabled', () => {
    const { container, getByText } = render(
      <ModalOverlay card>
        <p>Operation in progress</p>
      </ModalOverlay>,
    );

    fireEvent.click(container.querySelector('.modal-overlay')!);

    expect(getByText('Operation in progress')).toBeInTheDocument();
  });
});
