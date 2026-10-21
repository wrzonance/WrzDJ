import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import BuilderSettingsModal, { type BuilderSettings } from '../components/BuilderSettingsModal';

const settings: BuilderSettings = {
  suggestReplacements: false,
  confirmRecompute: true,
  confirmSlotRemoval: true,
  playOnDoubleClick: false,
  scrubOnCurveClick: true,
  showSlotMarkers: true,
  agentChimes: false,
  autoExpandPairings: true,
};

describe('BuilderSettingsModal', () => {
  it('does not render when closed', () => {
    render(
      <BuilderSettingsModal open={false} onClose={vi.fn()} autosave settings={settings}
        onAutosaveChange={vi.fn()} onSettingsChange={vi.fn()} />,
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('forwards autosave, settings patches, backdrop close, and dialog close', () => {
    const onClose = vi.fn();
    const onAutosaveChange = vi.fn();
    const onSettingsChange = vi.fn();
    render(
      <BuilderSettingsModal open onClose={onClose} autosave settings={settings}
        onAutosaveChange={onAutosaveChange} onSettingsChange={onSettingsChange} />,
    );

    fireEvent.click(screen.getByRole('checkbox', { name: /Autosave/ }));
    expect(onAutosaveChange).toHaveBeenCalledWith(false);
    fireEvent.click(screen.getByRole('checkbox', { name: /Energy mismatch prompt/ }));
    expect(onSettingsChange).toHaveBeenCalledWith({ ...settings, suggestReplacements: true });

    fireEvent.mouseDown(screen.getByRole('dialog').previousElementSibling!);
    expect(onClose).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
