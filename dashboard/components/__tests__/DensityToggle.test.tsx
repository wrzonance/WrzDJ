import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { DensityToggle } from '../DensityToggle';

describe('DensityToggle', () => {
  it('describes the current density and the action', () => {
    render(<DensityToggle compact={false} onToggle={vi.fn()} />);
    const btn = screen.getByRole('button', { name: 'Compact mode off' });
    expect(btn).toHaveAttribute('aria-pressed', 'false');
    expect(btn).toHaveTextContent('Normal');
    expect(btn).toHaveAttribute('title', 'Switch to compact density');
  });

  it('reflects compact mode', () => {
    render(<DensityToggle compact onToggle={vi.fn()} />);
    const btn = screen.getByRole('button', { name: 'Compact mode on' });
    expect(btn).toHaveAttribute('aria-pressed', 'true');
    expect(btn).toHaveTextContent('Dense');
    expect(btn).toHaveAttribute('title', 'Switch to normal density');
  });

  it('calls onToggle when clicked', () => {
    const onToggle = vi.fn();
    render(<DensityToggle compact={false} onToggle={onToggle} />);
    fireEvent.click(screen.getByRole('button', { name: 'Compact mode off' }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
