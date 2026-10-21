import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/api';
import { UsagePanel } from '../UsagePanel';
import type { LlmAdminUsage } from '@/lib/api/types';

vi.mock('@/lib/api', () => ({
  api: {
    getAdminLlmUsage: vi.fn(),
  },
}));

const emptyUsage: LlmAdminUsage = { days: 30, rows: [] };

describe('UsagePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows a distinct error and retries a failed usage request', async () => {
    // Regression for baseline 57cfcdc6867f: a rejected usage request was swallowed as an empty panel.
    vi.mocked(api.getAdminLlmUsage)
      .mockRejectedValueOnce(new Error('request failed'))
      .mockResolvedValueOnce(emptyUsage);

    render(<UsagePanel />);

    expect(await screen.findByText('Failed to load usage.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));

    await waitFor(() => expect(api.getAdminLlmUsage).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('No calls yet.')).toBeInTheDocument();
  });

  it('keeps a successful empty result distinct from a load failure', async () => {
    vi.mocked(api.getAdminLlmUsage).mockResolvedValue(emptyUsage);

    render(<UsagePanel />);

    expect(await screen.findByText('No calls yet.')).toBeInTheDocument();
    expect(screen.queryByText('Failed to load usage.')).not.toBeInTheDocument();
    expect(screen.getByText('Usage — last 30 days')).toBeInTheDocument();
  });
});
