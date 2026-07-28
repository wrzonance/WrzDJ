import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import SaveAsTemplateDialog from '../SaveAsTemplateDialog';
import type { SetSummary, SetTemplate } from '@/lib/api-types';

const mockSaveSetAsTemplate = vi.fn();
vi.mock('@/lib/api', () => ({
  api: {
    saveSetAsTemplate: (id: number, name: string) => mockSaveSetAsTemplate(id, name),
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

function makeTemplate(overrides: Partial<SetTemplate> = {}): SetTemplate {
  return {
    id: 3,
    name: 'Friday Wedding',
    vibe_theme: null,
    target_duration_sec: null,
    avg_transition_overlap_sec: 8,
    bpm_floor: null,
    bpm_ceiling: null,
    key_strictness: 0.2,
    slot_count: 0,
    curve_points: [],
    created_at: '2026-06-07T00:00:00Z',
    updated_at: '2026-06-07T00:00:00Z',
    ...overrides,
  };
}

describe('SaveAsTemplateDialog', () => {
  beforeEach(() => {
    mockSaveSetAsTemplate.mockReset();
  });

  it('pre-fills the name field with the set name', () => {
    render(<SaveAsTemplateDialog set={makeSet()} onClose={vi.fn()} onSaved={vi.fn()} />);
    expect(screen.getByDisplayValue('Friday Wedding')).toBeInTheDocument();
  });

  it('saves the trimmed name and calls onSaved with the new template', async () => {
    mockSaveSetAsTemplate.mockResolvedValue(makeTemplate());
    const onSaved = vi.fn();
    render(<SaveAsTemplateDialog set={makeSet()} onClose={vi.fn()} onSaved={onSaved} />);

    const input = screen.getByLabelText(/template name/i);
    fireEvent.change(input, { target: { value: '  Peak Hour Arc  ' } });
    fireEvent.click(screen.getByRole('button', { name: /save template/i }));

    await waitFor(() => {
      expect(mockSaveSetAsTemplate).toHaveBeenCalledWith(7, 'Peak Hour Arc');
    });
    expect(onSaved).toHaveBeenCalledWith(makeTemplate());
  });

  it('disables save when the name is blank', () => {
    render(<SaveAsTemplateDialog set={makeSet()} onClose={vi.fn()} onSaved={vi.fn()} />);
    const input = screen.getByLabelText(/template name/i);
    fireEvent.change(input, { target: { value: '   ' } });
    expect(screen.getByRole('button', { name: /save template/i })).toBeDisabled();
  });

  it('shows an error and keeps the dialog open when the save fails', async () => {
    mockSaveSetAsTemplate.mockRejectedValue(new Error('boom'));
    const onSaved = vi.fn();
    render(<SaveAsTemplateDialog set={makeSet()} onClose={vi.fn()} onSaved={onSaved} />);
    fireEvent.click(screen.getByRole('button', { name: /save template/i }));

    await waitFor(() => {
      expect(screen.getByText(/failed to save template/i)).toBeInTheDocument();
    });
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('calls onClose without saving when cancelled', () => {
    const onClose = vi.fn();
    render(<SaveAsTemplateDialog set={makeSet()} onClose={onClose} onSaved={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onClose).toHaveBeenCalled();
    expect(mockSaveSetAsTemplate).not.toHaveBeenCalled();
  });
});
