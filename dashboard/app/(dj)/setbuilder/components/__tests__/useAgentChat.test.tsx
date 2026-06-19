import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { formatAgentError, useAgentChat } from '../useAgentChat';
import type { BuilderCommit } from '../useSetDocumentHistory';

const mockApi = vi.hoisted(() => ({
  critiqueSet: vi.fn(),
  chatWithSetAgent: vi.fn(),
  getSetAgentHistory: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/api')>();
  return { api: mockApi, ApiError: original.ApiError };
});

function assistantMessage(overrides: Record<string, unknown> = {}) {
  return {
    id: 2,
    role: 'assistant',
    content: 'Swapped.',
    display_summary: 'Swapped.',
    tool_calls: [],
    affected_transition_scores: [],
    created_at: '2026-06-15T00:00:01Z',
    ...overrides,
  };
}

describe('useAgentChat', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.critiqueSet.mockResolvedValue({
      overall_grade: 'B+',
      summary: 'Strong opening, risky bridge.',
      flags: [],
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
      assistant_message: assistantMessage(),
      tool_calls: [],
      slots: [],
      affected_transition_scores: [],
    });
  });

  function mutatingResult() {
    return {
      message: 'Rebuilt.',
      assistant_message: assistantMessage({
        tool_calls: [
          {
            id: 'a1',
            name: 'autobuild',
            args: {},
            rationale: 'Rebuild from pool',
            result: {},
            mutating: true,
            display_summary: 'Rebuilt the set.',
          },
        ],
      }),
      tool_calls: [],
      slots: [],
      affected_transition_scores: [],
    };
  }

  it('routes a mutating turn through commit as one labeled undo entry', async () => {
    mockApi.chatWithSetAgent.mockResolvedValue(mutatingResult());
    const commit = vi.fn((...args: unknown[]) => (args[1] as () => Promise<unknown>)());
    const onMutationApplied = vi.fn();

    const { result } = renderHook(() =>
      useAgentChat(9, {
        open: true,
        onMutationApplied,
        commit: commit as unknown as BuilderCommit,
      }),
    );
    await act(async () => {
      await result.current.send('rebuild the set');
    });

    expect(commit).toHaveBeenCalledTimes(1);
    expect(commit.mock.calls[0][0]).toBe('Agent · rebuild the set');
    const shouldRecord = commit.mock.calls[0][2] as unknown as (r: {
      tool_calls: { mutating: boolean }[];
      assistant_message: { tool_calls: { mutating: boolean }[] };
    }) => boolean;
    expect(
      shouldRecord({ tool_calls: [], assistant_message: { tool_calls: [{ mutating: true }] } }),
    ).toBe(true);
    expect(
      shouldRecord({ tool_calls: [], assistant_message: { tool_calls: [{ mutating: false }] } }),
    ).toBe(false);
    expect(onMutationApplied).not.toHaveBeenCalled();
  });

  it('falls back to onMutationApplied when no commit is provided', async () => {
    mockApi.chatWithSetAgent.mockResolvedValue(mutatingResult());
    const onMutationApplied = vi.fn();

    const { result } = renderHook(() => useAgentChat(9, { open: true, onMutationApplied }));
    await act(async () => {
      await result.current.send('rebuild the set');
    });

    expect(onMutationApplied).toHaveBeenCalledTimes(1);
  });

  it('loads the critique on mount', async () => {
    const { result } = renderHook(() => useAgentChat(9, { open: false, onMutationApplied: vi.fn() }));
    await waitFor(() => expect(result.current.critique?.overall_grade).toBe('B+'));
    expect(mockApi.critiqueSet).toHaveBeenCalledWith(9);
  });

  it('loads history only after the surface opens', async () => {
    const { rerender } = renderHook(
      ({ open }) => useAgentChat(9, { open, onMutationApplied: vi.fn() }),
      { initialProps: { open: false } },
    );
    await waitFor(() => expect(mockApi.critiqueSet).toHaveBeenCalled());
    expect(mockApi.getSetAgentHistory).not.toHaveBeenCalled();

    rerender({ open: true });
    await waitFor(() => expect(mockApi.getSetAgentHistory).toHaveBeenCalledWith(9));
  });

  it('optimistically appends, replaces the pending entry, and clears input on send', async () => {
    const { result } = renderHook(() => useAgentChat(9, { open: true, onMutationApplied: vi.fn() }));
    await waitFor(() => expect(mockApi.getSetAgentHistory).toHaveBeenCalled());

    await act(async () => {
      await result.current.send('swap the opener');
    });

    expect(mockApi.chatWithSetAgent).toHaveBeenCalledWith(9, { message: 'swap the opener' });
    expect(result.current.input).toBe('');
    const roles = result.current.entries.map((entry) => entry.role);
    expect(roles).toEqual(['user', 'assistant']);
    expect(result.current.entries.every((entry) => !entry.pending)).toBe(true);
  });

  it('ignores a second send fired in the same tick (no duplicate request)', async () => {
    const { result } = renderHook(() => useAgentChat(9, { open: true, onMutationApplied: vi.fn() }));
    await waitFor(() => expect(mockApi.critiqueSet).toHaveBeenCalled());

    await act(async () => {
      await Promise.all([result.current.send('swap'), result.current.send('swap')]);
    });

    expect(mockApi.chatWithSetAgent).toHaveBeenCalledTimes(1);
  });

  it('notifies the parent when a mutating tool runs', async () => {
    const onMutationApplied = vi.fn();
    mockApi.chatWithSetAgent.mockResolvedValue({
      message: 'done',
      assistant_message: assistantMessage({
        tool_calls: [{ id: 1, name: 'reorder_slots', mutating: true }],
      }),
      tool_calls: [],
      slots: [],
      affected_transition_scores: [],
    });
    const { result } = renderHook(() => useAgentChat(9, { open: true, onMutationApplied }));
    await waitFor(() => expect(mockApi.getSetAgentHistory).toHaveBeenCalled());

    await act(async () => {
      await result.current.send('reorder');
    });

    expect(onMutationApplied).toHaveBeenCalledTimes(1);
  });

  it('does not notify the parent for read-only tool calls', async () => {
    const onMutationApplied = vi.fn();
    mockApi.chatWithSetAgent.mockResolvedValue({
      message: 'analysis',
      assistant_message: assistantMessage({
        tool_calls: [{ id: 1, name: 'critique_set', mutating: false }],
      }),
      tool_calls: [],
      slots: [],
      affected_transition_scores: [],
    });
    const { result } = renderHook(() => useAgentChat(9, { open: true, onMutationApplied }));
    await waitFor(() => expect(mockApi.getSetAgentHistory).toHaveBeenCalled());

    await act(async () => {
      await result.current.send('analyze');
    });

    expect(onMutationApplied).not.toHaveBeenCalled();
  });

  it('surfaces a friendly error and drops the pending entry on send failure', async () => {
    mockApi.chatWithSetAgent.mockRejectedValue(new Error('slot is locked'));
    const { result } = renderHook(() => useAgentChat(9, { open: true, onMutationApplied: vi.fn() }));
    await waitFor(() => expect(mockApi.getSetAgentHistory).toHaveBeenCalled());

    await act(async () => {
      await result.current.send('edit a locked slot');
    });

    expect(result.current.error).toMatch(/unlock/i);
    expect(result.current.entries).toHaveLength(0);
  });
});

describe('formatAgentError', () => {
  it('rewrites locked-slot failures into guidance', () => {
    expect(formatAgentError(new Error('the slot is locked'))).toMatch(/unlock/i);
  });

  it('passes through other error messages', () => {
    expect(formatAgentError(new Error('network down'))).toBe('network down');
  });

  it('falls back to a generic message for non-Error values', () => {
    expect(formatAgentError('nope')).toBe('Agent request failed');
  });
});
