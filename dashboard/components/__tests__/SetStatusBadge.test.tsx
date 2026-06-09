import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { SetStatusBadge } from '../SetStatusBadge';
import { SET_STATUS_META, getSetStatusMeta } from '@/lib/setbuilder-status';

describe('SetStatusBadge', () => {
  it.each(['draft', 'locked', 'exported'] as const)(
    'renders the %s status with its label and badge classes',
    (status) => {
      render(<SetStatusBadge status={status} />);
      const meta = SET_STATUS_META[status];
      const el = screen.getByText(meta.label);
      expect(el).toBeInTheDocument();
      for (const cls of meta.badgeClass.split(' ')) {
        expect(el).toHaveClass(cls);
      }
    }
  );

  it('exposes the status to assistive tech via aria-label', () => {
    render(<SetStatusBadge status="locked" />);
    expect(screen.getByLabelText('Status: Locked')).toBeInTheDocument();
  });

  it('adds the descriptive tooltip only when showTooltip is set', () => {
    const { rerender } = render(<SetStatusBadge status="draft" />);
    expect(screen.getByText('Draft')).not.toHaveAttribute('title');

    rerender(<SetStatusBadge status="draft" showTooltip />);
    expect(screen.getByText('Draft')).toHaveAttribute('title', SET_STATUS_META.draft.description);
  });

  it('falls back gracefully for an unrecognized status', () => {
    render(<SetStatusBadge status="banana" />);
    expect(screen.getByText(getSetStatusMeta('banana').label)).toBeInTheDocument();
  });
});
