import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ShareDialog from '../ShareDialog';
import type { SetSummary } from '@/lib/api-types';

const mockShareSet = vi.fn();
const mockRevokeSetShare = vi.fn();
vi.mock('@/lib/api', () => ({
  api: {
    shareSet: (id: number) => mockShareSet(id),
    revokeSetShare: (id: number) => mockRevokeSetShare(id),
  },
}));

function makeSet(overrides: Partial<SetSummary> = {}): SetSummary {
  return {
    id: 7,
    name: 'Friday Wedding',
    event_id: null,
    status: 'draft',
    sharing_mode: 'private',
    share_token: null,
    created_at: '2026-06-07T00:00:00Z',
    updated_at: '2026-06-07T00:00:00Z',
    ...overrides,
  };
}

describe('ShareDialog', () => {
  beforeEach(() => {
    mockShareSet.mockReset();
    mockRevokeSetShare.mockReset();
  });

  it('offers to create a share link when not shared', () => {
    render(<ShareDialog set={makeSet()} onClose={vi.fn()} onChanged={vi.fn()} />);
    expect(screen.getByRole('button', { name: /create share link/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /revoke/i })).not.toBeInTheDocument();
  });

  it('creates a link and surfaces the share URL', async () => {
    mockShareSet.mockResolvedValue({ share_token: 'tok_abc' });
    const onChanged = vi.fn();
    render(<ShareDialog set={makeSet()} onClose={vi.fn()} onChanged={onChanged} />);
    fireEvent.click(screen.getByRole('button', { name: /create share link/i }));
    await waitFor(() => {
      expect(screen.getByDisplayValue(/\/shared\/tok_abc$/)).toBeInTheDocument();
    });
    expect(mockShareSet).toHaveBeenCalledWith(7);
    expect(onChanged).toHaveBeenCalledWith('tok_abc');
  });

  it('shows the existing URL with regenerate and revoke when already shared', () => {
    render(
      <ShareDialog
        set={makeSet({ share_token: 'tok_live' })}
        onClose={vi.fn()}
        onChanged={vi.fn()}
      />
    );
    expect(screen.getByDisplayValue(/\/shared\/tok_live$/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /regenerate/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /revoke/i })).toBeInTheDocument();
  });

  it('revokes the link', async () => {
    mockRevokeSetShare.mockResolvedValue(undefined);
    const onChanged = vi.fn();
    render(
      <ShareDialog
        set={makeSet({ share_token: 'tok_live' })}
        onClose={vi.fn()}
        onChanged={onChanged}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /revoke/i }));
    await waitFor(() => {
      expect(mockRevokeSetShare).toHaveBeenCalledWith(7);
    });
    expect(onChanged).toHaveBeenCalledWith(null);
  });
});
