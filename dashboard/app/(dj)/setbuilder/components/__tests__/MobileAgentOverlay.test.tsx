import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import MobileAgentOverlay from '../MobileAgentOverlay';

const mockApi = vi.hoisted(() => ({
  critiqueSet: vi.fn(),
  chatWithSetAgent: vi.fn(),
  getSetAgentHistory: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/api')>();
  return { api: mockApi, ApiError: original.ApiError };
});

describe('MobileAgentOverlay', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.critiqueSet.mockResolvedValue({
      overall_grade: 'B+',
      summary: 'Strong opening, risky bridge.',
      flags: [{ type: 'energy_dip', slot_position: 2, message: 'Bridge drops too hard.' }],
    });
    mockApi.getSetAgentHistory.mockResolvedValue({
      messages: [],
      context_summary: null,
      compacted_through_message_id: null,
      uses_compact_context: true,
      recent_turn_limit: 12,
    });
    mockApi.chatWithSetAgent.mockResolvedValue({
      message: 'Swapped.',
      assistant_message: {
        id: 2,
        role: 'assistant',
        content: 'Swapped.',
        display_summary: 'Swapped.',
        tool_calls: [],
        affected_transition_scores: [],
        created_at: '2026-06-15T00:00:01Z',
      },
      tool_calls: [],
      slots: [],
      affected_transition_scores: [],
    });
  });

  it('shows the critique grade on the FAB before opening', async () => {
    render(<MobileAgentOverlay setId={9} onMutationApplied={vi.fn()} />);
    expect(await screen.findByTestId('agent-fab-grade')).toHaveTextContent('B+');
    // History is not fetched until the overlay opens.
    expect(mockApi.getSetAgentHistory).not.toHaveBeenCalled();
  });

  it('opens the full overlay from the FAB and loads history', async () => {
    render(<MobileAgentOverlay setId={9} onMutationApplied={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: /open agent/i }));

    expect(await screen.findByTestId('critique-card')).toBeInTheDocument();
    await waitFor(() => expect(mockApi.getSetAgentHistory).toHaveBeenCalledWith(9));
  });

  it('submits a message from the overlay composer', async () => {
    render(<MobileAgentOverlay setId={9} onMutationApplied={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: /open agent/i }));
    await screen.findByTestId('critique-card');

    fireEvent.change(screen.getByPlaceholderText(/tell the agent/i), {
      target: { value: 'swap the opener' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() =>
      expect(mockApi.chatWithSetAgent).toHaveBeenCalledWith(9, { message: 'swap the opener' }),
    );
  });

  it('closes the overlay with the close affordance', async () => {
    render(<MobileAgentOverlay setId={9} onMutationApplied={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: /open agent/i }));
    await screen.findByTestId('critique-card');

    fireEvent.click(screen.getByRole('button', { name: /close agent/i }));

    await waitFor(() => expect(screen.queryByTestId('critique-card')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: /open agent/i })).toBeInTheDocument();
  });

  it('switches persona from the overlay header', async () => {
    render(<MobileAgentOverlay setId={9} onMutationApplied={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: /open agent/i }));
    await screen.findByTestId('critique-card');

    // Peer persona renders the "Vibe check" critique title.
    expect(screen.getByText('Vibe check')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Pro' }));

    // Pro persona swaps the critique title and composer placeholder.
    expect(screen.getByText('Set Analysis')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/issue an instruction/i)).toBeInTheDocument();
  });

  it('renders the error fallback when critique loading fails', async () => {
    mockApi.critiqueSet.mockRejectedValue(new Error('boom'));
    render(<MobileAgentOverlay setId={9} onMutationApplied={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: /open agent/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/critique unavailable/i);
  });

  it('moves focus to the close button on open and restores it to the FAB on close', async () => {
    render(<MobileAgentOverlay setId={9} onMutationApplied={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: /open agent/i }));

    const closeButton = await screen.findByRole('button', { name: /close agent/i });
    await waitFor(() => expect(closeButton).toHaveFocus());

    fireEvent.click(closeButton);

    const fab = await screen.findByRole('button', { name: /open agent/i });
    await waitFor(() => expect(fab).toHaveFocus());
  });

  it('closes the overlay when Escape is pressed', async () => {
    render(<MobileAgentOverlay setId={9} onMutationApplied={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: /open agent/i }));
    await screen.findByTestId('critique-card');

    fireEvent.keyDown(window, { key: 'Escape' });

    await waitFor(() => expect(screen.queryByTestId('critique-card')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: /open agent/i })).toBeInTheDocument();
  });
});
