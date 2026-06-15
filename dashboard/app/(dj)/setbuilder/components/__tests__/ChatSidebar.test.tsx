import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ChatSidebar from '../ChatSidebar';

const mockApi = vi.hoisted(() => ({
  critiqueSet: vi.fn(),
  chatWithSetAgent: vi.fn(),
  getSetAgentHistory: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/api')>();
  return { api: mockApi, ApiError: original.ApiError };
});

describe('ChatSidebar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.critiqueSet.mockResolvedValue({
      overall_grade: 'B+',
      summary: 'Strong opening, risky bridge.',
      flags: [{ type: 'energy_dip', slot_position: 2, message: 'Bridge drops too hard.' }],
    });
    mockApi.chatWithSetAgent.mockResolvedValue({
      message: 'Swapped.',
      assistant_message: {
        id: 2,
        role: 'assistant',
        content: 'Swapped.',
        display_summary: 'Swapped.',
        tool_calls: [
          {
            id: 'swap-1',
            name: 'swap_slots',
            args: { slot_a_id: 1, slot_b_id: 2, rationale: 'Better opener' },
            rationale: 'Better opener',
            result: { slot_a_id: 1, slot_b_id: 2 },
            mutating: true,
            display_summary: 'Swapped slot 1 Track A with slot 2 Track B.',
          },
        ],
        affected_transition_scores: [{ slot_id: 2, position: 1, score: 88, warnings: [] }],
        created_at: '2026-06-15T00:00:01Z',
      },
      tool_calls: [
        {
          id: 'swap-1',
          name: 'swap_slots',
          args: { slot_a_id: 1, slot_b_id: 2, rationale: 'Better opener' },
          rationale: 'Better opener',
          result: { slot_a_id: 1, slot_b_id: 2 },
          mutating: true,
          display_summary: 'Swapped slot 1 Track A with slot 2 Track B.',
        },
      ],
      slots: [],
      affected_transition_scores: [{ slot_id: 2, position: 1, score: 88, warnings: [] }],
    });
    mockApi.getSetAgentHistory.mockResolvedValue({
      messages: [],
      context_summary: null,
      compacted_through_message_id: null,
      uses_compact_context: true,
      recent_turn_limit: 12,
    });
  });

  it('renders the auto critique card with grade and flags', async () => {
    render(<ChatSidebar setId={9} open onToggle={vi.fn()} onMutationApplied={vi.fn()} />);

    expect(await screen.findByTestId('critique-card')).toBeInTheDocument();
    expect(screen.getByText('B+')).toBeInTheDocument();
    expect(screen.getByText(/energy dip/i)).toBeInTheDocument();
    expect(mockApi.critiqueSet).toHaveBeenCalledWith(9);
  });

  it('loads persisted history without rendering raw tool JSON', async () => {
    mockApi.getSetAgentHistory.mockResolvedValue({
      messages: [
        {
          id: 1,
          role: 'user',
          content: 'swap the opener',
          display_summary: null,
          tool_calls: [],
          affected_transition_scores: [],
          created_at: '2026-06-15T00:00:00Z',
        },
        {
          id: 2,
          role: 'assistant',
          content: 'Swapped slot 1 Track A with slot 2 Track B.',
          display_summary: 'Swapped slot 1 Track A with slot 2 Track B.',
          tool_calls: [
            {
              id: 'swap-1',
              name: 'swap_slots',
              args: { slot_a_id: 1, slot_b_id: 2 },
              rationale: 'Better opener',
              result: { slot_a_id: 1, slot_b_id: 2 },
              mutating: true,
              display_summary: 'Swapped slot 1 Track A with slot 2 Track B.',
            },
          ],
          affected_transition_scores: [],
          created_at: '2026-06-15T00:00:01Z',
        },
      ],
      context_summary: 'Earlier: the set should start softer.',
      compacted_through_message_id: 2,
      uses_compact_context: true,
      recent_turn_limit: 12,
    });

    render(<ChatSidebar setId={9} open onToggle={vi.fn()} onMutationApplied={vi.fn()} />);

    expect(await screen.findByText('swap the opener')).toBeInTheDocument();
    expect(screen.getAllByText('Swapped slot 1 Track A with slot 2 Track B.')).toHaveLength(2);
    expect(screen.queryByText(/"slot_a_id"/)).not.toBeInTheDocument();
    expect(screen.getByText(/compact context/i)).toBeInTheDocument();
  });

  it('posts only the new message and renders returned summaries', async () => {
    mockApi.getSetAgentHistory.mockResolvedValue({
      messages: [],
      context_summary: null,
      compacted_through_message_id: null,
      uses_compact_context: true,
      recent_turn_limit: 12,
    });
    mockApi.chatWithSetAgent.mockResolvedValue({
      message: 'Swapped slot 1 Track A with slot 2 Track B.',
      assistant_message: {
        id: 2,
        role: 'assistant',
        content: 'Swapped slot 1 Track A with slot 2 Track B.',
        display_summary: 'Swapped slot 1 Track A with slot 2 Track B.',
        tool_calls: [],
        affected_transition_scores: [{ slot_id: 2, position: 1, score: 88, warnings: [] }],
        created_at: '2026-06-15T00:00:01Z',
      },
      tool_calls: [],
      slots: [],
      affected_transition_scores: [{ slot_id: 2, position: 1, score: 88, warnings: [] }],
    });

    const onMutationApplied = vi.fn();
    render(<ChatSidebar setId={9} open onToggle={vi.fn()} onMutationApplied={onMutationApplied} />);
    await screen.findByTestId('critique-card');

    fireEvent.change(screen.getByPlaceholderText(/tell the agent/i), {
      target: { value: 'swap the opener' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() =>
      expect(mockApi.chatWithSetAgent).toHaveBeenCalledWith(9, { message: 'swap the opener' }),
    );
    expect(await screen.findByText('Swapped slot 1 Track A with slot 2 Track B.')).toBeInTheDocument();
    expect(screen.queryByText(/"slot_a_id"/)).not.toBeInTheDocument();
    expect(onMutationApplied).not.toHaveBeenCalled();
  });
});
