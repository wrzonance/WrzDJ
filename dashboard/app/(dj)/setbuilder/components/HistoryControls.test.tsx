import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import HistoryControls from './HistoryControls';

describe('HistoryControls', () => {
  it('exposes the next history actions and keeps them unavailable while saving', () => {
    const onUndo = vi.fn();
    const onRedo = vi.fn();
    const onSettings = vi.fn();

    const { rerender } = render(
      <HistoryControls
        undoDepth={2}
        redoDepth={1}
        nextUndoLabel="Retarget slot 1"
        nextRedoLabel="Move slot 1"
        onUndo={onUndo}
        onRedo={onRedo}
        onSettings={onSettings}
        isSaving
      />,
    );

    const undo = screen.getByRole('button', { name: 'Undo: Retarget slot 1' });
    const redo = screen.getByRole('button', { name: 'Redo: Move slot 1' });
    expect(undo).toBeDisabled();
    expect(redo).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Open builder settings' })).toBeEnabled();

    rerender(
      <HistoryControls
        undoDepth={2}
        redoDepth={1}
        nextUndoLabel="Retarget slot 1"
        nextRedoLabel="Move slot 1"
        onUndo={onUndo}
        onRedo={onRedo}
        onSettings={onSettings}
        isSaving={false}
      />,
    );

    fireEvent.click(undo);
    fireEvent.click(redo);
    fireEvent.click(screen.getByRole('button', { name: 'Open builder settings' }));
    expect(onUndo).toHaveBeenCalledOnce();
    expect(onRedo).toHaveBeenCalledOnce();
    expect(onSettings).toHaveBeenCalledOnce();
  });

  it('disables history actions when their stacks are empty', () => {
    render(
      <HistoryControls
        undoDepth={0}
        redoDepth={0}
        nextUndoLabel={null}
        nextRedoLabel={null}
        onUndo={vi.fn()}
        onRedo={vi.fn()}
        onSettings={vi.fn()}
        isSaving={false}
      />,
    );

    expect(screen.getByRole('button', { name: 'Undo' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Redo' })).toBeDisabled();
  });
});
