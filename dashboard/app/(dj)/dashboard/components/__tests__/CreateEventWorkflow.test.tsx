import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LocaleProvider } from '@/lib/locale';
import { api } from '@/lib/api';
import { CreateEventWorkflow } from '../CreateEventWorkflow';

vi.mock('@/lib/api', () => ({
  api: {
    createEvent: vi.fn(),
    patchCollectionSettings: vi.fn(),
  },
}));

vi.mock('@/components/help/HelpSpot', () => ({
  HelpSpot: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

const createdEvent = {
  id: 7,
  code: 'EVT07',
  name: 'Launch Party',
} as never;

function renderWorkflow(onCreated = vi.fn(), onError = vi.fn()) {
  return {
    onCreated,
    onError,
    ...render(
      <LocaleProvider>
        <CreateEventWorkflow onCreated={onCreated} onError={onError} />
      </LocaleProvider>,
    ),
  };
}

describe('CreateEventWorkflow', () => {
  beforeEach(() => vi.clearAllMocks());

  it('creates the event before applying optional collection settings', async () => {
    vi.mocked(api.createEvent).mockResolvedValue(createdEvent);
    vi.mocked(api.patchCollectionSettings).mockResolvedValue({} as never);
    const { onCreated } = renderWorkflow();

    fireEvent.click(screen.getByRole('button', { name: 'Create Event' }));
    fireEvent.change(screen.getByLabelText('Event Name'), {
      target: { value: 'Launch Party' },
    });
    fireEvent.click(screen.getByLabelText('Enable pre-event voting'));
    fireEvent.change(screen.getByLabelText('Submission cap per guest'), {
      target: { value: '12' },
    });

    await act(async () => {
      fireEvent.submit(screen.getByRole('button', { name: 'Create' }));
    });

    expect(api.createEvent).toHaveBeenCalledWith('Launch Party');
    expect(onCreated).toHaveBeenCalledWith(createdEvent);
    expect(api.patchCollectionSettings).toHaveBeenCalledWith('EVT07', {
      collection_opens_at: null,
      live_starts_at: null,
      submission_cap_per_guest: 12,
    });
    await waitFor(() => expect(screen.queryByLabelText('Event Name')).not.toBeInTheDocument());
  });

  it('keeps the created event and reports when optional settings fail', async () => {
    vi.mocked(api.createEvent).mockResolvedValue(createdEvent);
    vi.mocked(api.patchCollectionSettings).mockRejectedValue(new Error('Settings unavailable'));
    const { onCreated, onError } = renderWorkflow();

    fireEvent.click(screen.getByRole('button', { name: 'Create Event' }));
    fireEvent.change(screen.getByLabelText('Event Name'), {
      target: { value: 'Launch Party' },
    });
    fireEvent.click(screen.getByLabelText('Enable pre-event voting'));
    fireEvent.change(screen.getByLabelText('Submission cap per guest'), {
      target: { value: '12' },
    });

    await act(async () => {
      fireEvent.submit(screen.getByRole('button', { name: 'Create' }));
    });

    expect(onCreated).toHaveBeenCalledWith(createdEvent);
    expect(onError).toHaveBeenCalledWith(expect.stringContaining('Settings unavailable'));
    expect(onError).toHaveBeenCalledWith(expect.stringContaining('Pre-Event Voting tab'));
    expect(screen.getByLabelText('Event Name')).toHaveValue('Launch Party');
  });
});
