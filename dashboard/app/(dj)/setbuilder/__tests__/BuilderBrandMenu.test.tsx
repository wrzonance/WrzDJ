import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import BuilderBrandMenu from '../components/BuilderBrandMenu';

function renderMenu(overrides: Partial<React.ComponentProps<typeof BuilderBrandMenu>> = {}) {
  const props = {
    name: 'Summer Set',
    isDirty: false,
    isSaving: false,
    saveError: null,
    lastSavedAt: new Date(Date.now() - 10_000),
    onSave: vi.fn(),
    onSettings: vi.fn(),
    ...overrides,
  };
  render(<BuilderBrandMenu {...props} />);
  return props;
}

describe('BuilderBrandMenu', () => {
  it('shows save state and opens the menu with save and settings actions', () => {
    const props = renderMenu();
    expect(screen.getByRole('button', { name: /Summer Set/ })).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(screen.getByRole('button', { name: /Summer Set/ }));

    expect(screen.getByRole('menu')).toBeInTheDocument();
    expect(screen.getByText('All saved')).toBeInTheDocument();
    expect(screen.getByText('10s ago')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('menuitem', { name: /All saved/ }));
    expect(props.onSave).toHaveBeenCalledOnce();
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('shows dirty/error details and disables save while a save is active', () => {
    renderMenu({ isDirty: true, isSaving: true, saveError: 'Network unavailable' });
    fireEvent.click(screen.getByRole('button', { name: /Summer Set/ }));
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
    expect(screen.getByText('Network unavailable')).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /Unsaved changes/ })).toBeDisabled();
  });

  it('closes from outside click or Escape and runs settings callback', () => {
    const props = renderMenu();
    fireEvent.click(screen.getByRole('button', { name: /Summer Set/ }));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Summer Set/ }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Settings' }));
    expect(props.onSettings).toHaveBeenCalledOnce();
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });
});
