import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { PairedKiosksCard } from '../PairedKiosksCard';

// Mock API — stable object reference to prevent useEffect re-triggers
const mockGetMyKiosks = vi.fn();
const mockRenameKiosk = vi.fn();
const mockDeleteKiosk = vi.fn();
vi.mock('@/lib/api', () => ({
  api: {
    getMyKiosks: (...args: unknown[]) => mockGetMyKiosks(...args),
    renameKiosk: (...args: unknown[]) => mockRenameKiosk(...args),
    deleteKiosk: (...args: unknown[]) => mockDeleteKiosk(...args),
  },
}));

describe('PairedKiosksCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetMyKiosks.mockResolvedValue([]);
    mockRenameKiosk.mockResolvedValue({});
    mockDeleteKiosk.mockResolvedValue(undefined);
  });

  it('renders empty state when no kiosks paired to this event', async () => {
    mockGetMyKiosks.mockResolvedValue([]);

    render(<PairedKiosksCard eventCode="EVT001" />);

    await waitFor(() => {
      expect(screen.getByText(/no kiosks paired/i)).toBeInTheDocument();
    });
  });

  it('renders kiosk list with names and status', async () => {
    mockGetMyKiosks.mockResolvedValue([
      {
        id: 1,
        name: 'Bar Kiosk',
        event_code: 'EVT001',
        event_name: 'Friday Night',
        status: 'active',
        paired_at: '2026-02-20T12:00:00Z',
        last_seen_at: '2026-02-20T12:05:00Z',
      },
      {
        id: 2,
        name: 'Stage Left',
        event_code: 'EVT001',
        event_name: 'Friday Night',
        status: 'disconnected',
        paired_at: '2026-02-20T11:00:00Z',
        last_seen_at: '2026-02-20T11:30:00Z',
      },
    ]);

    render(<PairedKiosksCard eventCode="EVT001" />);

    await waitFor(() => {
      expect(screen.getByText('Bar Kiosk')).toBeInTheDocument();
      expect(screen.getByText('Stage Left')).toBeInTheDocument();
    });
  });

  it('shows "Unnamed Kiosk" for null-name kiosks', async () => {
    mockGetMyKiosks.mockResolvedValue([
      {
        id: 1,
        name: null,
        event_code: 'EVT001',
        event_name: 'Friday Night',
        status: 'active',
        paired_at: '2026-02-20T12:00:00Z',
        last_seen_at: '2026-02-20T12:05:00Z',
      },
    ]);

    render(<PairedKiosksCard eventCode="EVT001" />);

    await waitFor(() => {
      expect(screen.getByText('Unnamed Kiosk')).toBeInTheDocument();
    });
  });

  it('filters kiosks to only show those for this event', async () => {
    mockGetMyKiosks.mockResolvedValue([
      {
        id: 1,
        name: 'Bar Kiosk',
        event_code: 'EVT001',
        event_name: 'Friday Night',
        status: 'active',
        paired_at: '2026-02-20T12:00:00Z',
        last_seen_at: '2026-02-20T12:05:00Z',
      },
      {
        id: 2,
        name: 'Other Venue',
        event_code: 'EVT002',
        event_name: 'Saturday Bash',
        status: 'active',
        paired_at: '2026-02-20T11:00:00Z',
        last_seen_at: '2026-02-20T11:30:00Z',
      },
    ]);

    render(<PairedKiosksCard eventCode="EVT001" />);

    await waitFor(() => {
      expect(screen.getByText('Bar Kiosk')).toBeInTheDocument();
    });
    // The other-event kiosk should not appear
    expect(screen.queryByText('Other Venue')).not.toBeInTheDocument();
  });

  it('calls deleteKiosk on unpair confirm', async () => {
    // Mock window.confirm
    const confirmSpy = vi.spyOn(globalThis, 'confirm').mockReturnValue(true);

    mockGetMyKiosks.mockResolvedValue([
      {
        id: 1,
        name: 'Bar Kiosk',
        event_code: 'EVT001',
        event_name: 'Friday Night',
        status: 'active',
        paired_at: '2026-02-20T12:00:00Z',
        last_seen_at: '2026-02-20T12:05:00Z',
      },
    ]);

    render(<PairedKiosksCard eventCode="EVT001" />);

    await waitFor(() => {
      expect(screen.getByText('Bar Kiosk')).toBeInTheDocument();
    });

    const unpairBtn = screen.getByRole('button', { name: /unpair/i });
    fireEvent.click(unpairBtn);

    await waitFor(() => {
      expect(mockDeleteKiosk).toHaveBeenCalledWith(1);
    });

    confirmSpy.mockRestore();
  });

  it('does not call deleteKiosk when confirm is cancelled', async () => {
    const confirmSpy = vi.spyOn(globalThis, 'confirm').mockReturnValue(false);

    mockGetMyKiosks.mockResolvedValue([
      {
        id: 1,
        name: 'Bar Kiosk',
        event_code: 'EVT001',
        event_name: 'Friday Night',
        status: 'active',
        paired_at: '2026-02-20T12:00:00Z',
        last_seen_at: '2026-02-20T12:05:00Z',
      },
    ]);

    render(<PairedKiosksCard eventCode="EVT001" />);

    await waitFor(() => {
      expect(screen.getByText('Bar Kiosk')).toBeInTheDocument();
    });

    const unpairBtn = screen.getByRole('button', { name: /unpair/i });
    fireEvent.click(unpairBtn);

    expect(mockDeleteKiosk).not.toHaveBeenCalled();

    confirmSpy.mockRestore();
  });

  it('renames kiosk via inline edit', async () => {
    mockGetMyKiosks.mockResolvedValue([
      {
        id: 1,
        name: 'Bar Kiosk',
        event_code: 'EVT001',
        event_name: 'Friday Night',
        status: 'active',
        paired_at: '2026-02-20T12:00:00Z',
        last_seen_at: '2026-02-20T12:05:00Z',
      },
    ]);
    mockRenameKiosk.mockResolvedValue({
      id: 1,
      name: 'VIP Lounge',
      event_code: 'EVT001',
      event_name: 'Friday Night',
      status: 'active',
      paired_at: '2026-02-20T12:00:00Z',
      last_seen_at: '2026-02-20T12:05:00Z',
    });

    render(<PairedKiosksCard eventCode="EVT001" />);

    await waitFor(() => {
      expect(screen.getByText('Bar Kiosk')).toBeInTheDocument();
    });

    // Click the rename button to enter edit mode
    const renameBtn = screen.getByRole('button', { name: /rename/i });
    fireEvent.click(renameBtn);

    // Find the input and change the value
    const input = screen.getByDisplayValue('Bar Kiosk');
    fireEvent.change(input, { target: { value: 'VIP Lounge' } });

    // Submit the rename (press Enter or click save)
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => {
      expect(mockRenameKiosk).toHaveBeenCalledWith(1, 'VIP Lounge');
    });
  });

  it('shows pairing instructions', async () => {
    mockGetMyKiosks.mockResolvedValue([]);

    render(<PairedKiosksCard eventCode="EVT001" />);

    await waitFor(() => {
      expect(screen.getByText(/kiosk-pair/i)).toBeInTheDocument();
    });
  });
});
