import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import DJLayout from '../layout';

let mockPathname = '/dashboard';
vi.mock('next/navigation', () => ({
  usePathname: () => mockPathname,
}));

vi.mock('@/components/ThemeToggle', () => ({
  ThemeToggle: () => <button data-testid="theme-toggle-mock">Theme</button>,
}));

describe('DJLayout', () => {
  it('renders the floating theme toggle on regular DJ pages', () => {
    mockPathname = '/dashboard';
    render(
      <DJLayout>
        <div>content</div>
      </DJLayout>,
    );
    expect(screen.getByTestId('theme-toggle-mock')).toBeInTheDocument();
  });

  it('suppresses the floating toggle on /setbuilder routes (rendered inline there instead)', () => {
    mockPathname = '/setbuilder/42';
    render(
      <DJLayout>
        <div>content</div>
      </DJLayout>,
    );
    expect(screen.queryByTestId('theme-toggle-mock')).not.toBeInTheDocument();
  });

  it('renders children regardless of route', () => {
    mockPathname = '/setbuilder';
    render(
      <DJLayout>
        <div data-testid="child">content</div>
      </DJLayout>,
    );
    expect(screen.getByTestId('child')).toBeInTheDocument();
  });
});
