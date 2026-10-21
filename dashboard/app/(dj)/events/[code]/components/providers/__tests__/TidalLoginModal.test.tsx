import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { TidalLoginModal } from '../TidalLoginModal';

describe('TidalLoginModal', () => {
  it('shows the user code, safe login URL, and polling status', () => {
    render(
      <TidalLoginModal
        loginUrl="https://login.tidal.com/device"
        userCode="ABCD-1234"
        polling
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByRole('link', { name: 'Open Tidal Login' })).toHaveAttribute(
      'href',
      'https://login.tidal.com/device',
    );
    const loginLink = screen.getByRole('link', { name: 'Open Tidal Login' });
    expect(loginLink.style.background).toBe('rgb(0, 102, 255)');
    expect(loginLink.style.color).toBe('var(--text-on-bright-accent)');
    expect(screen.getByText('ABCD-1234')).toBeInTheDocument();
    expect(screen.getByText('Waiting for authorization...')).toBeInTheDocument();
  });

  it('rejects a dangerous login scheme and still allows cancel', () => {
    const onCancel = vi.fn();
    render(
      <TidalLoginModal
        loginUrl="javascript:alert(1)"
        userCode="ABCD"
        polling={false}
        onCancel={onCancel}
      />,
    );

    expect(screen.getByRole('link', { name: 'Open Tidal Login' })).toHaveAttribute('href', '#');
    expect(screen.queryByText('Waiting for authorization...')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
