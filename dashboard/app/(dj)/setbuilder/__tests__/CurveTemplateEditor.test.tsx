import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll } from 'vitest';
import CurveTemplateEditorOverlay from '../components/CurveTemplateEditorOverlay';
import type { CurvePoint } from '@/lib/api-types';

beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

const POINTS: CurvePoint[] = [
  { t: 0, e: 3, label: 'Start', slow_start: false, slow_end: false },
  { t: 0.5, e: 8, label: 'Peak', slow_start: false, slow_end: false },
  { t: 1, e: 5, label: 'End', slow_start: false, slow_end: false },
];

function renderOverlay(over: Partial<React.ComponentProps<typeof CurveTemplateEditorOverlay>> = {}) {
  const props: React.ComponentProps<typeof CurveTemplateEditorOverlay> = {
    open: true,
    mode: 'create',
    initial: null,
    isBuiltIn: false,
    onSaveNew: vi.fn(),
    onSaveCurrent: vi.fn(),
    onDelete: vi.fn(),
    onClose: vi.fn(),
    ...over,
  };
  return { ...render(<CurveTemplateEditorOverlay {...props} />), props };
}

describe('CurveTemplateEditorOverlay', () => {
  it('renders nothing when closed', () => {
    renderOverlay({ open: false });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('starts blank in create mode with 3 default points', () => {
    renderOverlay();
    expect(screen.getByTestId('point-count')).toHaveTextContent('3');
    expect(screen.getByLabelText('Template name')).toHaveValue('Untitled curve');
  });

  it('loads an existing template for editing and saves changes', () => {
    const onSaveCurrent = vi.fn();
    renderOverlay({
      mode: 'edit',
      initial: { id: 9, name: 'My Curve', points: POINTS },
      onSaveCurrent,
    });
    fireEvent.change(screen.getByLabelText('Template name'), { target: { value: 'Renamed' } });
    fireEvent.click(screen.getByTestId('template-save'));
    expect(onSaveCurrent).toHaveBeenCalledTimes(1);
    expect(onSaveCurrent.mock.calls[0][0]).toMatchObject({ id: 9, name: 'Renamed' });
  });

  it('built-in templates offer save-as-copy only, with read-only badge', () => {
    const onSaveNew = vi.fn();
    renderOverlay({
      mode: 'edit',
      isBuiltIn: true,
      initial: { name: 'Wedding', points: POINTS },
      onSaveNew,
    });
    expect(screen.getByText('read-only original')).toBeInTheDocument();
    expect(screen.queryByTestId('template-save')).not.toBeInTheDocument();
    expect(screen.queryByTestId('template-delete')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Template name')).toHaveValue('Wedding (copy)');
    fireEvent.click(screen.getByTestId('template-save-as'));
    expect(onSaveNew).toHaveBeenCalledTimes(1);
    expect(onSaveNew.mock.calls[0][0].name).toBe('Wedding (copy)');
  });

  it('removes interior points but never endpoints', () => {
    renderOverlay({ mode: 'edit', initial: { id: 1, name: 'X', points: POINTS } });
    expect(screen.getByTestId('point-count')).toHaveTextContent('3');
    // endpoints have no delete button
    expect(screen.queryByTestId('point-del-0')).not.toBeInTheDocument();
    expect(screen.queryByTestId('point-del-2')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('point-del-1'));
    expect(screen.getByTestId('point-count')).toHaveTextContent('2');
  });

  it('deletes a user template after confirm', () => {
    const onDelete = vi.fn();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderOverlay({
      mode: 'edit',
      initial: { id: 4, name: 'Old', points: POINTS },
      onDelete,
    });
    fireEvent.click(screen.getByTestId('template-delete'));
    expect(onDelete).toHaveBeenCalledWith(4);
  });

  it('escape closes the overlay', () => {
    const onClose = vi.fn();
    renderOverlay({ onClose });
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});
