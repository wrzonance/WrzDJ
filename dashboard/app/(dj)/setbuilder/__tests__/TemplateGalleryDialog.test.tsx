import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import TemplateGalleryDialog from '../TemplateGalleryDialog';
import type { SetDetail, SetTemplate } from '@/lib/api-types';

const mockListSetTemplates = vi.fn();
const mockInstantiateSetTemplate = vi.fn();
const mockDeleteSetTemplate = vi.fn();
vi.mock('@/lib/api', () => ({
  api: {
    listSetTemplates: () => mockListSetTemplates(),
    instantiateSetTemplate: (id: number) => mockInstantiateSetTemplate(id),
    deleteSetTemplate: (id: number) => mockDeleteSetTemplate(id),
  },
}));

function makeTemplate(overrides: Partial<SetTemplate> = {}): SetTemplate {
  return {
    id: 3,
    name: 'Peak Hour Arc',
    vibe_theme: null,
    target_duration_sec: 3600,
    avg_transition_overlap_sec: 8,
    bpm_floor: null,
    bpm_ceiling: null,
    key_strictness: 0.2,
    slot_count: 12,
    curve_points: [
      { position_sec: 0, energy: 3, label: null, is_slow_window_start: false, is_slow_window_end: false },
      { position_sec: 1800, energy: 8, label: 'Peak', is_slow_window_start: false, is_slow_window_end: false },
    ],
    created_at: '2026-06-07T00:00:00Z',
    updated_at: '2026-06-07T00:00:00Z',
    ...overrides,
  };
}

function makeSetDetail(overrides: Partial<SetDetail> = {}): SetDetail {
  return {
    id: 9,
    name: 'Peak Hour Arc',
    event_id: null,
    status: 'draft',
    sharing_mode: 'private',
    share_token: null,
    created_at: '2026-06-08T00:00:00Z',
    updated_at: '2026-06-08T00:00:00Z',
    vibe_theme: null,
    target_duration_sec: 3600,
    avg_transition_overlap_sec: 8,
    bpm_floor: null,
    bpm_ceiling: null,
    key_strictness: 0.2,
    tidal_playlist_id: null,
    exported_at: null,
    ...overrides,
  };
}

describe('TemplateGalleryDialog', () => {
  beforeEach(() => {
    mockListSetTemplates.mockReset();
    mockInstantiateSetTemplate.mockReset();
    mockDeleteSetTemplate.mockReset();
  });

  it('shows a loading state while the gallery fetches', () => {
    mockListSetTemplates.mockReturnValue(new Promise(() => {}));
    render(<TemplateGalleryDialog onClose={vi.fn()} onInstantiated={vi.fn()} />);
    expect(screen.getByText(/loading templates/i)).toBeInTheDocument();
  });

  it('renders the empty state when there are no saved templates', async () => {
    mockListSetTemplates.mockResolvedValue({ templates: [] });
    render(<TemplateGalleryDialog onClose={vi.fn()} onInstantiated={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText(/no templates saved yet/i)).toBeInTheDocument();
    });
  });

  it('renders template cards with slot and curve-point counts', async () => {
    mockListSetTemplates.mockResolvedValue({ templates: [makeTemplate()] });
    render(<TemplateGalleryDialog onClose={vi.fn()} onInstantiated={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText('Peak Hour Arc')).toBeInTheDocument();
      expect(screen.getByText('12 slots')).toBeInTheDocument();
      expect(screen.getByText('2 curve points')).toBeInTheDocument();
    });
  });

  it('shows an error when the gallery fails to load', async () => {
    mockListSetTemplates.mockRejectedValue(new Error('boom'));
    render(<TemplateGalleryDialog onClose={vi.fn()} onInstantiated={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText(/failed to load templates/i)).toBeInTheDocument();
    });
  });

  it('instantiates a template and calls onInstantiated with the new set', async () => {
    mockListSetTemplates.mockResolvedValue({ templates: [makeTemplate()] });
    mockInstantiateSetTemplate.mockResolvedValue(makeSetDetail());
    const onInstantiated = vi.fn();
    render(<TemplateGalleryDialog onClose={vi.fn()} onInstantiated={onInstantiated} />);

    await waitFor(() => expect(screen.getByText('Peak Hour Arc')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /use template/i }));

    await waitFor(() => {
      expect(mockInstantiateSetTemplate).toHaveBeenCalledWith(3);
      expect(onInstantiated).toHaveBeenCalledWith(makeSetDetail());
    });
  });

  it('shows an error and does not call onInstantiated when instantiate fails', async () => {
    mockListSetTemplates.mockResolvedValue({ templates: [makeTemplate()] });
    mockInstantiateSetTemplate.mockRejectedValue(new Error('boom'));
    const onInstantiated = vi.fn();
    render(<TemplateGalleryDialog onClose={vi.fn()} onInstantiated={onInstantiated} />);

    await waitFor(() => expect(screen.getByText('Peak Hour Arc')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /use template/i }));

    await waitFor(() => {
      expect(screen.getByText(/failed to create set from template/i)).toBeInTheDocument();
    });
    expect(onInstantiated).not.toHaveBeenCalled();
  });

  it('deletes a template after confirmation and removes it from the list', async () => {
    mockListSetTemplates.mockResolvedValue({ templates: [makeTemplate()] });
    mockDeleteSetTemplate.mockResolvedValue(undefined);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<TemplateGalleryDialog onClose={vi.fn()} onInstantiated={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('Peak Hour Arc')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /delete/i }));

    await waitFor(() => {
      expect(mockDeleteSetTemplate).toHaveBeenCalledWith(3);
      expect(screen.queryByText('Peak Hour Arc')).not.toBeInTheDocument();
    });
  });

  it('does not delete the template when the confirmation is cancelled', async () => {
    mockListSetTemplates.mockResolvedValue({ templates: [makeTemplate()] });
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<TemplateGalleryDialog onClose={vi.fn()} onInstantiated={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('Peak Hour Arc')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /delete/i }));

    await waitFor(() => {
      expect(mockDeleteSetTemplate).not.toHaveBeenCalled();
      expect(screen.getByText('Peak Hour Arc')).toBeInTheDocument();
    });
  });

  it('calls onClose without any API side effects when Close is clicked', async () => {
    mockListSetTemplates.mockResolvedValue({ templates: [] });
    const onClose = vi.fn();
    render(<TemplateGalleryDialog onClose={onClose} onInstantiated={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/no templates saved yet/i)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /close/i }));

    expect(onClose).toHaveBeenCalled();
    expect(mockInstantiateSetTemplate).not.toHaveBeenCalled();
    expect(mockDeleteSetTemplate).not.toHaveBeenCalled();
  });
  it('locks every card while one instantiation is in flight, so no duplicate set is created', async () => {
    // Two cards: per-card busy state alone would leave the SECOND card's
    // buttons live while the first is still creating a set.
    mockListSetTemplates.mockResolvedValue({
      templates: [makeTemplate({ id: 1, name: 'First Arc' }), makeTemplate({ id: 2, name: 'Second Arc' })],
    });
    let resolveInstantiate: (v: SetDetail) => void = () => {};
    mockInstantiateSetTemplate.mockReturnValue(
      new Promise<SetDetail>((resolve) => {
        resolveInstantiate = resolve;
      })
    );
    const onInstantiated = vi.fn();
    const onClose = vi.fn();
    render(<TemplateGalleryDialog onClose={onClose} onInstantiated={onInstantiated} />);

    await waitFor(() => expect(screen.getByText('First Arc')).toBeInTheDocument());
    const useButtons = screen.getAllByRole('button', { name: /use template/i });
    fireEvent.click(useButtons[0]);

    await waitFor(() => expect(mockInstantiateSetTemplate).toHaveBeenCalledTimes(1));

    // Every action — including the other card's and the delete buttons — is disabled.
    screen
      .getAllByRole('button', { name: /use template|creating|delete/i })
      .forEach((btn) => expect(btn).toBeDisabled());

    // Clicking the second card again must not fire a second request.
    fireEvent.click(useButtons[1]);
    fireEvent.click(screen.getAllByRole('button', { name: /delete/i })[0]);
    expect(mockInstantiateSetTemplate).toHaveBeenCalledTimes(1);
    expect(mockDeleteSetTemplate).not.toHaveBeenCalled();

    // Close is inert while mutating.
    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(onClose).not.toHaveBeenCalled();

    resolveInstantiate(makeSetDetail());
    await waitFor(() => expect(onInstantiated).toHaveBeenCalledTimes(1));
  });
});
