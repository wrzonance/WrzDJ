'use client';

import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '@/lib/api';
import type { AgentChatMessage, AgentChatOut, SetCritique } from '@/lib/api-types';
import type { BuilderCommit } from './useSetDocumentHistory';

export type Persona = 'peer' | 'pro';

export type ChatEntry = Pick<
  AgentChatMessage,
  'id' | 'role' | 'content' | 'display_summary' | 'tool_calls' | 'affected_transition_scores'
> & { pending?: boolean };

export interface AgentChatController {
  persona: Persona;
  setPersona: (persona: Persona) => void;
  critique: SetCritique | null;
  entries: ChatEntry[];
  historyMeta: { usesCompactContext: boolean; recentTurnLimit: number } | null;
  input: string;
  setInput: (value: string) => void;
  busy: boolean;
  error: string | null;
  suggestions: string[];
  send: (override?: string) => Promise<void>;
}

const PEER_SUGGESTIONS = [
  'Why is the weakest transition flagged?',
  'Make the slow window land softer',
  'Find a better bridge from the pool',
  'Cut one track with least damage',
];

const PRO_SUGGESTIONS = [
  'Analyze transition 2',
  'Recompute critique from current set',
  'Bump the peak energy by 0.5',
  'Surface risky BPM jumps',
];

export function formatAgentError(error: unknown): string {
  const message = error instanceof Error ? error.message : 'Agent request failed';
  if (/locked/i.test(message)) {
    return 'Skipped because a locked slot would be changed. Unlock that slot before editing it.';
  }
  return message;
}

/**
 * Owns all WrzDJSet agent-chat state and side effects (critique load, history
 * load, message send). Shared by the desktop sidebar and the mobile overlay so
 * exactly one instance mounts and fetches at a time.
 *
 * Capabilities & limitations:
 * - Critique loads on mount and whenever `setId`/`refreshToken` change.
 * - History loads only while `open` is true; stale responses are discarded via
 *   a monotonic request id so a fast reopen never clobbers fresher state.
 * - Sends are one-at-a-time: a synchronous in-flight guard rejects overlapping
 *   `send()` calls, so the same tick can never fire duplicate requests.
 * - No retry or streaming: a failed send surfaces a normalized error message and
 *   removes its optimistic pending entry.
 */
export function useAgentChat(
  setId: number,
  {
    open,
    refreshToken = 0,
    onMutationApplied,
    commit,
  }: {
    open: boolean;
    refreshToken?: number;
    onMutationApplied: () => void;
    commit?: BuilderCommit;
  },
): AgentChatController {
  const [persona, setPersona] = useState<Persona>('peer');
  const [critique, setCritique] = useState<SetCritique | null>(null);
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [historyMeta, setHistoryMeta] = useState<{
    usesCompactContext: boolean;
    recentTurnLimit: number;
  } | null>(null);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const historyRequestIdRef = useRef(0);
  const historyErrorRef = useRef<string | null>(null);
  const hasLocalTurnRef = useRef(false);
  const sendInFlightRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api
      .critiqueSet(setId)
      .then((result) => {
        if (!cancelled) setCritique(result);
      })
      .catch((err) => {
        if (cancelled) return;
        setCritique(null);
        setError(
          err instanceof ApiError && err.status === 400 ? err.message : 'Critique unavailable',
        );
      });
    return () => {
      cancelled = true;
    };
  }, [setId, refreshToken]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const requestId = historyRequestIdRef.current + 1;
    historyRequestIdRef.current = requestId;
    hasLocalTurnRef.current = false;

    api
      .getSetAgentHistory(setId)
      .then((history) => {
        if (cancelled || historyRequestIdRef.current !== requestId) return;
        if (!hasLocalTurnRef.current) {
          setEntries(history.messages);
        }
        setHistoryMeta({
          usesCompactContext: history.uses_compact_context,
          recentTurnLimit: history.recent_turn_limit,
        });
        const staleHistoryError = historyErrorRef.current;
        setError((current) => (current === staleHistoryError ? null : current));
        historyErrorRef.current = null;
      })
      .catch((err) => {
        if (cancelled || historyRequestIdRef.current !== requestId) return;
        const message = err instanceof Error ? err.message : 'Agent history unavailable';
        historyErrorRef.current = message;
        setError(message);
      });
    return () => {
      cancelled = true;
    };
  }, [open, setId]);

  const suggestions = persona === 'peer' ? PEER_SUGGESTIONS : PRO_SUGGESTIONS;

  const send = async (override?: string) => {
    const message = (override ?? input).trim();
    if (!message || busy || sendInFlightRef.current) return;
    sendInFlightRef.current = true;
    hasLocalTurnRef.current = true;
    const pendingEntry: ChatEntry = {
      id: -Date.now(),
      role: 'user',
      content: message,
      display_summary: null,
      tool_calls: [],
      affected_transition_scores: [],
      pending: true,
    };
    setEntries((prev) => [...prev, pendingEntry]);
    setInput('');
    setBusy(true);
    setError(null);
    try {
      const didMutate = (res: AgentChatOut) =>
        [...res.tool_calls, ...res.assistant_message.tool_calls].some((tool) => tool.mutating);
      const label = `Agent · ${message.slice(0, 40)}`;
      const action = () => api.chatWithSetAgent(setId, { message });
      const result = commit ? await commit(label, action, didMutate) : await action();
      setEntries((prev) => [
        ...prev.filter((entry) => entry.id !== pendingEntry.id),
        {
          id: pendingEntry.id,
          role: 'user',
          content: message,
          display_summary: null,
          tool_calls: [],
          affected_transition_scores: [],
        },
        result.assistant_message,
      ]);
      // With commit, the published snapshot bumps snapshotVersion and the
      // workspace reloads; only the no-history fallback needs the manual refresh.
      if (!commit && didMutate(result)) onMutationApplied();
    } catch (err) {
      setEntries((prev) => prev.filter((entry) => entry.id !== pendingEntry.id));
      setError(formatAgentError(err));
    } finally {
      setBusy(false);
      sendInFlightRef.current = false;
    }
  };

  return {
    persona,
    setPersona,
    critique,
    entries,
    historyMeta,
    input,
    setInput,
    busy,
    error,
    suggestions,
    send,
  };
}
