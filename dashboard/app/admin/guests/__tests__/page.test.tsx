import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import AdminGuestsPage from '../page';

vi.mock('@/lib/help/HelpContext', () => ({
  useHelp: () => ({
    helpMode: false,
    onboardingActive: false,
    currentStep: 0,
    activeSpotId: null,
    toggleHelpMode: vi.fn(),
    registerSpot: vi.fn(() => vi.fn()),
    getSpotsForPage: vi.fn(() => []),
    startOnboarding: vi.fn(),
    nextStep: vi.fn(),
    prevStep: vi.fn(),
    skipOnboarding: vi.fn(),
    hasSeenPage: vi.fn(() => true),
  }),
}));

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      getAdminGuests: vi.fn(),
      updateAdminGuest: vi.fn(),
      updateAdminGuestProfile: vi.fn(),
      deleteAdminGuest: vi.fn(),
    },
  };
});

import { api, ApiError } from '@/lib/api';

const NOW = Date.now();
const hoursAgo = (h: number) => new Date(NOW - h * 3_600_000).toISOString();

const alice = {
  id: 1,
  nickname: 'Alice',
  browser: 'Safari · iOS',
  email_verified: true,
  email_masked: 'a***@example.com',
  email_verified_at: hoursAgo(30),
  human_verified_at: hoursAgo(2),
  human_verify_count: 2,
  fingerprint_short: 'abc123def456',
  fingerprint_shared_with: 0,
  created_at: hoursAgo(48),
  last_seen_at: hoursAgo(1),
  event_count: 1,
  request_count: 3,
  events: [
    {
      event_id: 10,
      code: 'TEST01',
      name: 'Test Event',
      nickname: 'Alice',
      submission_count: 3,
      joined_at: hoursAgo(47),
    },
  ],
};

const bob = {
  id: 2,
  nickname: 'bob_1',
  browser: 'Chrome · Android',
  email_verified: false,
  email_masked: null,
  email_verified_at: null,
  human_verified_at: null,
  human_verify_count: 0,
  fingerprint_short: 'abc123def456',
  fingerprint_shared_with: 1,
  created_at: hoursAgo(5),
  last_seen_at: hoursAgo(4),
  event_count: 0,
  request_count: 0,
  events: [],
};

const ghost = {
  ...bob,
  id: 3,
  nickname: null,
  browser: null,
  fingerprint_short: null,
  fingerprint_shared_with: 0,
};

const mockPage = { items: [alice, bob, ghost], total: 3, page: 1, limit: 20 };

async function renderLoaded() {
  render(<AdminGuestsPage />);
  await waitFor(() => {
    expect(screen.getByText('Alice')).toBeInTheDocument();
  });
}

describe('AdminGuestsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getAdminGuests).mockResolvedValue(mockPage);
  });

  it('renders the heading and the four filter tabs', async () => {
    await renderLoaded();

    expect(screen.getByRole('heading', { name: 'Guest Management' })).toBeInTheDocument();
    for (const label of ['All', 'Verified', 'Unverified', 'Shared fingerprint']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
  });

  it('shows email, human, and fingerprint signals per guest', async () => {
    await renderLoaded();

    // The filter tabs are also named "Verified"/"Unverified"; scope to the table.
    const table = within(screen.getByRole('table'));
    expect(table.getByText('a***@example.com')).toBeInTheDocument();
    expect(table.getByText('Verified')).toBeInTheDocument();
    expect(table.getAllByText('Unverified')).toHaveLength(2);
    expect(table.getByText('2 passes')).toBeInTheDocument();
    expect(table.getAllByText('Never')).toHaveLength(2);
    expect(table.getByText('Unique')).toBeInTheDocument();
    expect(table.getByText('Shared ×1')).toBeInTheDocument();
    expect(table.getByText('None')).toBeInTheDocument();
    expect(table.getByText('No name yet')).toBeInTheDocument();
    expect(table.getByText('Safari · iOS')).toBeInTheDocument();
  });

  it('expands a row to list event memberships', async () => {
    await renderLoaded();

    expect(screen.queryByText('TEST01')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '1 event' }));

    const detail = screen.getByRole('list', { name: 'Events joined by Alice' });
    expect(within(detail).getByText('TEST01')).toBeInTheDocument();
    expect(within(detail).getByText('Test Event')).toBeInTheDocument();
    expect(within(detail).getByText('3 submissions')).toBeInTheDocument();
  });

  it('disables the events toggle for a guest with no memberships', async () => {
    await renderLoaded();

    expect(screen.getAllByRole('button', { name: '0 events' })[0]).toBeDisabled();
  });

  it('searches by nickname after a short pause', async () => {
    await renderLoaded();

    fireEvent.change(screen.getByLabelText('Search by nickname'), { target: { value: 'ali' } });

    await waitFor(() => {
      expect(api.getAdminGuests).toHaveBeenLastCalledWith(1, 20, 'all', 'ali');
    });
  });

  it('loads exactly once on mount', async () => {
    await renderLoaded();

    expect(api.getAdminGuests).toHaveBeenCalledTimes(1);
  });

  it('keeps the newer filter result when an older request resolves later', async () => {
    let resolveFirst: (value: typeof mockPage) => void = () => {};
    const first = new Promise<typeof mockPage>((resolve) => {
      resolveFirst = resolve;
    });
    const sharedPage = { items: [bob], total: 1, page: 1, limit: 20 };
    vi.mocked(api.getAdminGuests)
      .mockImplementationOnce(() => first)
      .mockResolvedValue(sharedPage);

    render(<AdminGuestsPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Shared fingerprint' }));
    await waitFor(() => {
      expect(screen.getByText('bob_1')).toBeInTheDocument();
    });

    resolveFirst(mockPage);
    await new Promise((r) => setTimeout(r, 0));

    expect(screen.queryByText('Alice')).not.toBeInTheDocument();
    expect(screen.getByText('bob_1')).toBeInTheDocument();
  });

  it('returns to the previous page after deleting the last guest on a later page', async () => {
    vi.mocked(api.deleteAdminGuest).mockResolvedValue(undefined);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    let deleted = false;
    vi.mocked(api.getAdminGuests).mockImplementation(async (page) => {
      if (page === 2 && !deleted) return { items: [bob], total: 21, page: 2, limit: 20 };
      if (page === 2) return { items: [], total: 20, page: 2, limit: 20 };
      return { items: [alice], total: deleted ? 20 : 21, page: 1, limit: 20 };
    });

    await renderLoaded();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => {
      expect(screen.getByText('bob_1')).toBeInTheDocument();
    });

    deleted = true;
    fireEvent.click(screen.getAllByRole('button', { name: 'Delete' })[0]);

    await waitFor(() => {
      expect(api.getAdminGuests).toHaveBeenLastCalledWith(1, 20, 'all', undefined);
    });
    expect(screen.getByText('Alice')).toBeInTheDocument();
  });

  it('reloads with the chosen filter', async () => {
    await renderLoaded();

    fireEvent.click(screen.getByRole('button', { name: 'Shared fingerprint' }));

    await waitFor(() => {
      expect(api.getAdminGuests).toHaveBeenLastCalledWith(1, 20, 'shared', undefined);
    });
  });

  it('saves a changed per-event nickname and nothing else', async () => {
    vi.mocked(api.updateAdminGuestProfile).mockResolvedValue({ ...alice, nickname: 'Zed' });
    await renderLoaded();

    fireEvent.click(screen.getAllByRole('button', { name: 'Edit' })[0]);
    expect(screen.getByText('Edit: Alice')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Nickname in Test Event'), { target: { value: 'Zed' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(api.updateAdminGuestProfile).toHaveBeenCalledWith(1, 10, { nickname: 'Zed' });
    });
    expect(api.updateAdminGuest).not.toHaveBeenCalled();
  });

  it('revokes the verified email from the edit modal', async () => {
    vi.mocked(api.updateAdminGuest).mockResolvedValue({ ...alice, email_verified: false });
    await renderLoaded();

    fireEvent.click(screen.getAllByRole('button', { name: 'Edit' })[0]);
    fireEvent.click(screen.getByLabelText('Revoke verified email'));
    fireEvent.submit(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(api.updateAdminGuest).toHaveBeenCalledWith(1, { revoke_email: true });
    });
    expect(api.updateAdminGuestProfile).not.toHaveBeenCalled();
  });

  it('does not offer email revocation for an unverified guest', async () => {
    await renderLoaded();

    fireEvent.click(screen.getAllByRole('button', { name: 'Edit' })[1]);

    expect(screen.getByText('Edit: bob_1')).toBeInTheDocument();
    expect(screen.queryByLabelText('Revoke verified email')).not.toBeInTheDocument();
  });

  it('keeps the modal open and shows the conflict on a 409', async () => {
    vi.mocked(api.updateAdminGuestProfile).mockRejectedValue(
      new ApiError('Nickname already taken in this event', 409),
    );
    await renderLoaded();

    fireEvent.click(screen.getAllByRole('button', { name: 'Edit' })[0]);
    fireEvent.change(screen.getByLabelText('Nickname in Test Event'), { target: { value: 'bob_1' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(screen.getByText('Nickname already taken in this event')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument();
  });

  describe('edit dialog accessibility', () => {
    async function openAliceEdit() {
      await renderLoaded();
      const editButton = screen.getAllByRole('button', { name: 'Edit' })[0];
      editButton.focus();
      fireEvent.click(editButton);
      return editButton;
    }

    it('names the dialog after the guest', async () => {
      await openAliceEdit();

      expect(screen.getByRole('dialog', { name: /Edit: Alice/ })).toBeInTheDocument();
    });

    it('moves focus to the first nickname input on open', async () => {
      await openAliceEdit();

      const dialog = screen.getByRole('dialog');
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
      expect(screen.getByLabelText('Nickname in Test Event')).toHaveFocus();
    });

    it('wraps Tab from Cancel to the first field and Shift+Tab back', async () => {
      await openAliceEdit();
      const cancel = screen.getByRole('button', { name: 'Cancel' });
      cancel.focus();

      fireEvent.keyDown(cancel, { key: 'Tab' });
      expect(screen.getByLabelText('Nickname in Test Event')).toHaveFocus();

      fireEvent.keyDown(document.activeElement as Element, { key: 'Tab', shiftKey: true });
      expect(cancel).toHaveFocus();
    });

    it('restores focus to the Edit button when Cancel closes the dialog', async () => {
      const editButton = await openAliceEdit();

      fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(editButton).toHaveFocus();
    });

    it('restores focus to the Edit button when Escape closes the dialog', async () => {
      const editButton = await openAliceEdit();

      fireEvent.keyDown(window, { key: 'Escape' });

      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(editButton).toHaveFocus();
    });
  });

  it('deletes a guest after confirmation', async () => {
    vi.mocked(api.deleteAdminGuest).mockResolvedValue(undefined);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    await renderLoaded();

    fireEvent.click(screen.getAllByRole('button', { name: 'Delete' })[0]);

    expect(window.confirm).toHaveBeenCalledWith(
      'Delete guest "Alice"? Their event memberships are removed; their requests and votes stay but become anonymous.',
    );
    await waitFor(() => {
      expect(api.deleteAdminGuest).toHaveBeenCalledWith(1);
    });
  });

  it('does not delete when the confirmation is rejected', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    await renderLoaded();

    fireEvent.click(screen.getAllByRole('button', { name: 'Delete' })[0]);

    expect(api.deleteAdminGuest).not.toHaveBeenCalled();
  });

  it('shows the empty state when nothing matches', async () => {
    vi.mocked(api.getAdminGuests).mockResolvedValue({ items: [], total: 0, page: 1, limit: 20 });

    render(<AdminGuestsPage />);

    await waitFor(() => {
      expect(screen.getByText('No guests match this filter.')).toBeInTheDocument();
    });
  });

  it('shows an error when loading fails', async () => {
    vi.mocked(api.getAdminGuests).mockRejectedValue(new Error('Network error'));

    render(<AdminGuestsPage />);

    await waitFor(() => {
      expect(screen.getByText('Failed to load guests')).toBeInTheDocument();
    });
  });
});
