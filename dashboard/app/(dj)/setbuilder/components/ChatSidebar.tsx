'use client';

import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '@/lib/api';
import type {
  AgentChatMessage,
  AppliedToolCall,
  SetCritique,
  TransitionScore,
} from '@/lib/api-types';
import styles from '../setbuilder.module.css';

type Persona = 'peer' | 'pro';

type ChatEntry = Pick<
  AgentChatMessage,
  'id' | 'role' | 'content' | 'display_summary' | 'tool_calls' | 'affected_transition_scores'
> & { pending?: boolean };

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

function flagTone(type: string): string {
  if (type === 'transition_brilliant') return styles.flagBrilliant;
  if (type === 'energy_dip' || type === 'banger_buried' || type === 'vibe_clash') {
    return styles.flagDanger;
  }
  return styles.flagWarn;
}

function formatFlag(type: string): string {
  return type.replaceAll('_', ' ');
}

function ToolCard({ tool }: { tool: AppliedToolCall }) {
  const toolName = tool.name.replaceAll('_', ' ');
  const rationale = tool.rationale?.trim() ?? '';
  const summary = tool.display_summary.trim() || rationale || toolName;

  return (
    <div className={styles.toolCallCard} data-testid="agent-tool-card">
      <span className={styles.toolName}>{toolName}</span>
      <div className={styles.toolBody}>
        <div className={styles.toolSummary}>{summary}</div>
        {rationale && rationale !== summary && <div className={styles.toolRationale}>{rationale}</div>}
      </div>
    </div>
  );
}

function CritiqueCard({ critique, persona }: { critique: SetCritique; persona: Persona }) {
  return (
    <div className={styles.critiqueCard} data-testid="critique-card">
      <div className={styles.critiqueHeader}>
        <div className={styles.critiqueGrade}>{critique.overall_grade}</div>
        <div>
          <div className={styles.critiqueTitle}>
            {persona === 'peer' ? 'Vibe check' : 'Set Analysis'}
          </div>
          <div className={styles.critiqueSub}>
            {persona === 'peer'
              ? 'Quick read on the timeline'
              : 'Computed against curve, pool, and transition scores'}
          </div>
        </div>
      </div>
      <div className={styles.critiqueSummary}>{critique.summary || 'No summary returned.'}</div>
      <div className={styles.critiqueFlags}>
        {critique.flags.length === 0 ? (
          <span className={styles.flagChip}>no flags</span>
        ) : (
          critique.flags.map((flag, i) => (
            <span key={`${flag.type}-${i}`} className={`${styles.flagChip} ${flagTone(flag.type)}`}>
              {formatFlag(flag.type)}
              {flag.slot_position != null ? ` · ${flag.slot_position + 1}` : ''}
            </span>
          ))
        )}
      </div>
    </div>
  );
}

export default function ChatSidebar({
  setId,
  open,
  onToggle,
  refreshToken = 0,
  onMutationApplied,
}: {
  setId: number;
  open: boolean;
  onToggle: () => void;
  refreshToken?: number;
  onMutationApplied: () => void;
}) {
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
  const scrollRef = useRef<HTMLDivElement>(null);
  const historyRequestIdRef = useRef(0);
  const historyErrorRef = useRef<string | null>(null);
  const hasLocalTurnRef = useRef(false);

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
        setError(err instanceof ApiError && err.status === 400 ? err.message : 'Critique unavailable');
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

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [entries, busy]);

  const suggestions = persona === 'peer' ? PEER_SUGGESTIONS : PRO_SUGGESTIONS;

  const send = async (override?: string) => {
    const message = (override ?? input).trim();
    if (!message || busy) return;
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
      const result = await api.chatWithSetAgent(setId, { message });
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
      const mutatingTools = [...result.tool_calls, ...result.assistant_message.tool_calls];
      if (mutatingTools.some((tool) => tool.mutating)) onMutationApplied();
    } catch (err) {
      setEntries((prev) => prev.filter((entry) => entry.id !== pendingEntry.id));
      setError(err instanceof Error ? err.message : 'Agent request failed');
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <button className={`${styles.panel} ${styles.chatCollapsed}`} onClick={onToggle}>
        <span className={styles.chatCollapsedLabel}>Agent</span>
        {critique?.overall_grade && <span className={styles.chatCollapsedGrade}>{critique.overall_grade}</span>}
      </button>
    );
  }

  return (
    <section className={`${styles.panel} ${styles.chatSection}`} aria-label="Agent chat">
      <div className={styles.chatHeader}>
        <div className={styles.panelHeaderInline}>Agent</div>
        <div className={styles.personaToggle} aria-label="Agent personality">
          <button
            className={persona === 'peer' ? styles.personaActive : ''}
            onClick={() => setPersona('peer')}
          >
            Peer
          </button>
          <button
            className={persona === 'pro' ? styles.personaActive : ''}
            onClick={() => setPersona('pro')}
          >
            Pro
          </button>
        </div>
        <button className="btn btn-sm" onClick={onToggle}>
          Collapse
        </button>
      </div>

      {historyMeta && (
        <div className={styles.chatContextMeta}>
          {historyMeta.usesCompactContext
            ? `Uses compact context + last ${historyMeta.recentTurnLimit} turns`
            : 'Uses recent turns'}
        </div>
      )}
      {critique && <CritiqueCard critique={critique} persona={persona} />}
      {error && <div className={styles.chatError}>{error}</div>}

      <div className={styles.chatScroll} ref={scrollRef}>
        {entries.length === 0 && (
          <div className={styles.chatEmpty}>Ask the agent to critique, explain, or edit the timeline.</div>
        )}
        {entries.map((entry) => (
          <div
            key={entry.id}
            className={`${styles.chatMessage} ${entry.role === 'user' ? styles.chatUser : styles.chatAgent}`}
          >
            <div className={styles.chatAuthor}>
              {entry.role === 'user'
                ? 'You'
                : persona === 'peer'
                  ? 'WrzDJ Agent'
                  : 'WrzDJSet Assistant'}
            </div>
            <div className={styles.chatBubble}>{entry.display_summary || entry.content}</div>
            {entry.tool_calls?.map((tool) => <ToolCard key={tool.id} tool={tool} />)}
            {entry.affected_transition_scores && entry.affected_transition_scores.length > 0 && (
              <div className={styles.scoreUpdate}>
                {entry.affected_transition_scores.map((score: TransitionScore) => (
                  <span key={score.slot_id}>
                    slot {score.position + 1}: {Math.round(score.score)}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && <div className={styles.chatEmpty}>Agent is thinking...</div>}
      </div>

      <div className={styles.chatComposer}>
        <div className={styles.chatSuggestions}>
          {suggestions.map((suggestion) => (
            <button key={suggestion} className={styles.suggestionChip} onClick={() => send(suggestion)}>
              {suggestion}
            </button>
          ))}
        </div>
        <div className={styles.chatInputWrap}>
          <textarea
            className={styles.chatInput}
            value={input}
            placeholder={persona === 'peer' ? 'tell the agent what to fix...' : 'Issue an instruction...'}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={1}
          />
          <button className={styles.chatSend} disabled={!input.trim() || busy} onClick={() => send()}>
            Send
          </button>
        </div>
      </div>
    </section>
  );
}
