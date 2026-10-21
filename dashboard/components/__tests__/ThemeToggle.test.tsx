import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { ThemeToggle } from '../ThemeToggle';

const toggleTheme = vi.fn();

vi.mock('@/lib/theme', () => ({
  useTheme: () => ({ theme: 'dark', toggleTheme }),
}));

describe('ThemeToggle', () => {
  it('names the current theme and the action', () => {
    render(<ThemeToggle />);
    const btn = screen.getByRole('button', { name: 'Current theme: Dark. Click to change.' });
    expect(btn).toHaveTextContent('Dark');
    expect(btn).toHaveAttribute('type', 'button');
  });

  it('cycles the theme on click', () => {
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole('button', { name: /current theme/i }));
    expect(toggleTheme).toHaveBeenCalledTimes(1);
  });
});
