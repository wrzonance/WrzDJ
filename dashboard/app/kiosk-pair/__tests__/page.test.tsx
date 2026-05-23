import { render, screen, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import KioskPairPage from '../page';

// Mock next/navigation
const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

// Mock qrcode.react
vi.mock('qrcode.react', () => ({
  QRCodeSVG: ({ value }: { value: string }) => (
    <div data-testid="qr-code" data-value={value}>QR Code</div>
  ),
}));

// Mock API
const mockGetKioskPairChallenge = vi.fn();
const mockCreateKioskPairing = vi.fn();
const mockGetKioskPairStatus = vi.fn();
const mockGetKioskAssignment = vi.fn();
vi.mock('@/lib/api', () => ({
  api: {
    getKioskPairChallenge: (...args: unknown[]) => mockGetKioskPairChallenge(...args),
    createKioskPairing: (...args: unknown[]) => mockCreateKioskPairing(...args),
    getKioskPairStatus: (...args: unknown[]) => mockGetKioskPairStatus(...args),
    getKioskAssignment: (...args: unknown[]) => mockGetKioskAssignment(...args),
  },
}));

// Mock localStorage
const mockStorage: Record<string, string> = {};
const mockLocalStorage = {
  getItem: vi.fn((key: string) => mockStorage[key] ?? null),
  setItem: vi.fn((key: string, value: string) => { mockStorage[key] = value; }),
  removeItem: vi.fn((key: string) => { delete mockStorage[key]; }),
};
Object.defineProperty(globalThis, 'localStorage', { value: mockLocalStorage, writable: true });

describe('KioskPairPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.keys(mockStorage).forEach(k => delete mockStorage[k]);
    mockGetKioskPairChallenge.mockResolvedValue({
      nonce: 'test-nonce-abc123',
      expires_in: 10,
    });
    mockCreateKioskPairing.mockResolvedValue({
      pair_code: 'ABC234',
      session_token: 'a'.repeat(64),
      expires_at: new Date(Date.now() + 5 * 60 * 1000).toISOString(),
    });
    // Default: pairing polls return "still pairing" so intervals don't redirect
    mockGetKioskPairStatus.mockResolvedValue({
      status: 'pairing',
      event_code: null,
      event_name: null,
    });
    mockGetKioskAssignment.mockResolvedValue({
      status: 'pairing',
      event_code: null,
      event_name: null,
    });
  });

  it('displays formatted pair code as XXX-XXX', async () => {
    render(<KioskPairPage />);

    await waitFor(() => {
      expect(screen.getByText('ABC-234')).toBeInTheDocument();
    });
  });

  it('renders QR code with correct URL', async () => {
    render(<KioskPairPage />);

    await waitFor(() => {
      const qr = screen.getByTestId('qr-code');
      expect(qr.getAttribute('data-value')).toContain('/kiosk-link/ABC234');
    });
  });

  it('stores session token in localStorage', async () => {
    render(<KioskPairPage />);

    await waitFor(() => {
      expect(mockLocalStorage.setItem).toHaveBeenCalledWith(
        'kiosk_session_token',
        'a'.repeat(64)
      );
    });
  });

  it('fetches challenge nonce and passes it to createKioskPairing', async () => {
    render(<KioskPairPage />);

    await waitFor(() => {
      expect(mockGetKioskPairChallenge).toHaveBeenCalled();
      expect(mockCreateKioskPairing).toHaveBeenCalledWith('test-nonce-abc123');
    });
  });

  it('redirects to display page when pairing completes', async () => {
    // First call returns pairing, second returns active
    mockGetKioskPairStatus
      .mockResolvedValueOnce({ status: 'pairing', event_code: null, event_name: null })
      .mockResolvedValue({ status: 'active', event_code: 'EVT001', event_join_code: 'EVT01J', event_name: 'Friday Night' });

    render(<KioskPairPage />);

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/e/EVT01J/display');
    }, { timeout: 5000 });
  });

  it('shows expired state and auto-regenerates when code expires', async () => {
    mockGetKioskPairStatus.mockResolvedValue({
      status: 'expired',
      event_code: null,
      event_name: null,
    });

    render(<KioskPairPage />);

    await waitFor(() => {
      expect(screen.getByText('Pairing code expired')).toBeInTheDocument();
      expect(screen.getByText('Generating new code...')).toBeInTheDocument();
    }, { timeout: 5000 });
  });

  it('polls assignment endpoint when existing token found', async () => {
    mockStorage['kiosk_session_token'] = 'b'.repeat(64);
    mockGetKioskAssignment.mockResolvedValue({
      status: 'active',
      event_code: 'EVT002',
      event_join_code: 'EVT02J',
      event_name: 'Saturday',
    });

    await act(async () => {
      render(<KioskPairPage />);
    });

    await waitFor(() => {
      expect(mockGetKioskAssignment).toHaveBeenCalledWith('b'.repeat(64));
    });

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/e/EVT02J/display');
    });
  });
});
