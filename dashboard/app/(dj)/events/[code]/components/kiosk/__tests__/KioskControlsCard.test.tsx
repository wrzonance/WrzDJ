import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { KioskControlsCard } from '../KioskControlsCard';

const props: React.ComponentProps<typeof KioskControlsCard> = {
  joinCode: 'GUEST123',
  controls: {
    requestsOpen: true,
    togglingRequests: false,
    onToggleRequests: vi.fn(),
    nowPlayingHidden: false,
    togglingNowPlaying: false,
    onToggleNowPlaying: vi.fn(),
    autoHideInput: '5',
    autoHideMinutes: 5,
    savingAutoHide: false,
    onAutoHideInputChange: vi.fn(),
    onSaveAutoHide: vi.fn(),
    kioskDisplayOnly: false,
    togglingDisplayOnly: false,
    onToggleDisplayOnly: vi.fn(),
    frictionlessJoin: false,
    togglingFrictionless: false,
    onToggleFrictionless: vi.fn(),
  },
};

describe('KioskControlsCard', () => {
  it('uses the public join code for preview and delegates visible controls', () => {
    const onToggleRequests = vi.fn();
    const onToggleNowPlaying = vi.fn();
    const onToggleDisplayOnly = vi.fn();
    const onToggleFrictionless = vi.fn();
    render(
      <KioskControlsCard
        {...props}
        controls={{
          ...props.controls,
          onToggleRequests,
          onToggleNowPlaying,
          onToggleDisplayOnly,
          onToggleFrictionless,
        }}
      />,
    );

    expect(screen.getByRole('link', { name: 'Preview Kiosk' })).toHaveAttribute('href', '/e/GUEST123/display');
    fireEvent.click(screen.getByRole('button', { name: 'Open' }));
    fireEvent.click(screen.getByRole('button', { name: 'Visible' }));
    fireEvent.click(screen.getByRole('button', { name: 'Off' }));
    fireEvent.click(screen.getByRole('button', { name: 'Frictionless join: Off' }));

    expect(onToggleRequests).toHaveBeenCalledOnce();
    expect(onToggleNowPlaying).toHaveBeenCalledOnce();
    expect(onToggleDisplayOnly).toHaveBeenCalledOnce();
    expect(onToggleFrictionless).toHaveBeenCalledOnce();
  });

  it('forwards auto-hide changes and only offers save for a valid changed value', () => {
    const onAutoHideInputChange = vi.fn();
    const onSaveAutoHide = vi.fn();
    const { rerender } = render(
      <KioskControlsCard {...props} controls={{ ...props.controls, onAutoHideInputChange, onSaveAutoHide }} />,
    );

    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
    const autoHideInput = screen.getByRole('spinbutton');
    expect(autoHideInput).toHaveAttribute('min', '1');
    expect(autoHideInput).toHaveAttribute('max', '1440');
    fireEvent.change(autoHideInput, { target: { value: '10' } });
    expect(onAutoHideInputChange).toHaveBeenCalledWith('10');
    rerender(
      <KioskControlsCard
        {...props}
        controls={{
          ...props.controls,
          autoHideInput: '10',
          onAutoHideInputChange,
          onSaveAutoHide,
        }}
      />,
    );
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
  });

  it('disables toggles while their corresponding saves are in progress', () => {
    render(
      <KioskControlsCard
        {...props}
        controls={{
          ...props.controls,
          togglingRequests: true,
          togglingNowPlaying: true,
          togglingDisplayOnly: true,
          togglingFrictionless: true,
          autoHideInput: '1441',
        }}
      />,
    );

    expect(screen.getAllByRole('button', { name: '...' })).toHaveLength(4);
    expect(screen.getAllByRole('button', { name: '...' }).every((button) => button.hasAttribute('disabled'))).toBe(true);
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
  });
});
