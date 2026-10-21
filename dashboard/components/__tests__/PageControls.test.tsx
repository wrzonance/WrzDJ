import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { PageControls } from '../PageControls';

vi.mock('@/components/ThemeToggle', () => ({
  ThemeToggle: () => <button data-testid="theme-toggle">Theme</button>,
}));

vi.mock('@/components/help/HelpButton', () => ({
  HelpButton: ({ page }: { page: string }) => <button data-testid="help-button">{page}</button>,
}));

describe('PageControls', () => {
  it('renders a single toolbar holding the theme toggle', () => {
    render(<PageControls />);
    const toolbar = screen.getByRole('toolbar', { name: 'Page controls' });
    expect(toolbar).toContainElement(screen.getByTestId('theme-toggle'));
    expect(screen.queryByTestId('help-button')).not.toBeInTheDocument();
  });

  it('adds the help button for the given page, after the theme toggle', () => {
    render(<PageControls helpPage="dashboard" />);
    const toolbar = screen.getByRole('toolbar', { name: 'Page controls' });
    const help = screen.getByTestId('help-button');
    expect(help).toHaveTextContent('dashboard');
    const order = Array.from(toolbar.querySelectorAll('button')).map((b) => b.dataset.testid);
    expect(order).toEqual(['theme-toggle', 'help-button']);
  });

  it('places page-specific controls before the shared ones', () => {
    render(
      <PageControls helpPage="event-manage">
        <button data-testid="density">Density</button>
      </PageControls>,
    );
    const toolbar = screen.getByRole('toolbar', { name: 'Page controls' });
    const order = Array.from(toolbar.querySelectorAll('button')).map((b) => b.dataset.testid);
    expect(order).toEqual(['density', 'theme-toggle', 'help-button']);
  });
});
