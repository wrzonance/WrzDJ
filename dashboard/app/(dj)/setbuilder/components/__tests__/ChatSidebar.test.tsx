import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ChatSidebar from '../ChatSidebar';

const mockApi = vi.hoisted(() => ({
  critiqueSet: vi.fn(),
  chatWithSetAgent: vi.fn(),
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
      tool_calls: [
        {
          id: 'swap-1',
          name: 'swap_slots',
          args: { slot_a_id: 1, slot_b_id: 2, rationale: 'Better opener' },
          rationale: 'Better opener',
          result: { slot_a_id: 1, slot_b_id: 2 },
          mutating: true,
        },
      ],
      slots: [],
      affected_transition_scores: [{ slot_id: 2, position: 1, score: 88, warnings: [] }],
    });
  });

  it('renders the auto critique card with grade and flags', async () => {
    render(<ChatSidebar setId={9} open onToggle={vi.fn()} onMutationApplied={vi.fn()} />);

    expect(await screen.findByTestId('critique-card')).toBeInTheDocument();
    expect(screen.getByText('B+')).toBeInTheDocument();
    expect(screen.getByText(/energy dip/i)).toBeInTheDocument();
    expect(mockApi.critiqueSet).toHaveBeenCalledWith(9);
  });

  it('renders tool-call args and rationale after a mutating agent turn', async () => {
    const onMutationApplied = vi.fn();
    render(<ChatSidebar setId={9} open onToggle={vi.fn()} onMutationApplied={onMutationApplied} />);
    await screen.findByTestId('critique-card');

    fireEvent.change(screen.getByPlaceholderText(/tell the agent/i), {
      target: { value: 'swap the opener' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => expect(mockApi.chatWithSetAgent).toHaveBeenCalledTimes(1));
    expect(await screen.findByTestId('agent-tool-card')).toHaveTextContent('swap_slots');
    expect(screen.getByTestId('agent-tool-card')).toHaveTextContent('"slot_a_id":1');
    expect(screen.getByTestId('agent-tool-card')).toHaveTextContent('Better opener');
    expect(screen.getByText(/slot 2: 88/i)).toBeInTheDocument();
    expect(onMutationApplied).toHaveBeenCalledTimes(1);
  });
});
