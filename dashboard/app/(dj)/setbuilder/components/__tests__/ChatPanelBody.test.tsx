import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ChatPanelBody from '../ChatPanelBody';
import type { AgentChatController } from '../useAgentChat';

function makeController(overrides: Partial<AgentChatController> = {}): AgentChatController {
  return {
    persona: 'peer',
    setPersona: vi.fn(),
    critique: {
      overall_grade: 'B+',
      summary: 'Strong opening, risky bridge.',
      flags: [{ type: 'energy_dip', slot_position: 2, message: 'Bridge drops too hard.' }],
    },
    entries: [],
    historyMeta: { usesCompactContext: true, recentTurnLimit: 12 },
    input: '',
    setInput: vi.fn(),
    busy: false,
    error: null,
    suggestions: ['Make the slow window land softer'],
    send: vi.fn(),
    ...overrides,
  } as AgentChatController;
}

describe('ChatPanelBody', () => {
  it('renders the critique card with grade and flags', () => {
    render(<ChatPanelBody chat={makeController()} />);
    expect(screen.getByTestId('critique-card')).toBeInTheDocument();
    expect(screen.getByText('B+')).toBeInTheDocument();
    expect(screen.getByText(/energy dip/i)).toBeInTheDocument();
  });

  it('renders a persisted tool call without raw JSON', () => {
    const chat = makeController({
      entries: [
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
        },
      ],
    });
    render(<ChatPanelBody chat={chat} />);
    expect(screen.getByTestId('agent-tool-card')).toHaveTextContent('swap slots');
    expect(screen.queryByText(/"slot_a_id"/)).not.toBeInTheDocument();
  });

  it('sends a suggestion chip when tapped', () => {
    const send = vi.fn();
    render(<ChatPanelBody chat={makeController({ send })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Make the slow window land softer' }));
    expect(send).toHaveBeenCalledWith('Make the slow window land softer');
  });

  it('submits the typed message via the Send button', () => {
    const send = vi.fn();
    render(<ChatPanelBody chat={makeController({ input: 'swap the opener', send })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(send).toHaveBeenCalledTimes(1);
  });
});
