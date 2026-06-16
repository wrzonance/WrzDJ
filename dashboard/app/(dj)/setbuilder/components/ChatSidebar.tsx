'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError } from '@/lib/api';
import type { AppliedToolCall, SetCritique, TransitionScore } from '@/lib/api-types';
import styles from '../setbuilder.module.css';

type Persona = 'peer' | 'pro';

interface ChatEntry {
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: AppliedToolCall[];
  transitionScores?: TransitionScore[];
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

function formatAgentError(error: unknown): string {
  const message = error instanceof Error ? error.message : 'Agent request failed';
  if (/locked/i.test(message)) {
    return 'Skipped because a locked slot would be changed. Unlock that slot before editing it.';
  }
  return message;
}

function lockSkipReasons(tool: AppliedToolCall): string[] {
  const result = tool.result;
  if (!result || typeof result !== 'object') return [];
  const data = result as Record<string, unknown>;
  const skipped = data.skipped_slots ?? data.skippedSlots ?? data.skipped;
  if (!Array.isArray(skipped)) return [];
  return skipped
    .map((item) => {
      if (!item || typeof item !== 'object') return null;
      const reason = 'reason' in item ? String(item.reason ?? '') : '';
      if (!/lock/i.test(reason)) return null;
      const slot =
        'slot_position' in item && typeof item.slot_position === 'number'
          ? `slot ${item.slot_position + 1}`
          : 'a slot';
      return `Skipped ${slot} because it is locked.`;
    })
    .filter((reason): reason is string => Boolean(reason));
}

function ToolCard({ tool }: { tool: AppliedToolCall }) {
  const args = JSON.stringify(tool.args);
  const skippedLocks = lockSkipReasons(tool);
  return (
    <div className={styles.toolCallCard} data-testid="agent-tool-card">
      <span className={styles.toolName}>{tool.name}</span>
      <div className={styles.toolBody}>
        <div className={styles.toolArgs}>{args}</div>
        {tool.rationale && <div className={styles.toolRationale}>&quot;{tool.rationale}&quot;</div>}
        {skippedLocks.map((reason) => (
          <div key={reason} className={styles.toolRationale} data-testid="agent-lock-skip">
            {reason}
          </div>
        ))}
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
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

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
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [entries, busy]);

  const suggestions = persona === 'peer' ? PEER_SUGGESTIONS : PRO_SUGGESTIONS;
  const history = useMemo(
    () =>
      entries
        .filter((entry) => entry.content.trim())
        .slice(-30)
        .map((entry) => ({ role: entry.role, content: entry.content })),
    [entries],
  );

  const send = async (override?: string) => {
    const message = (override ?? input).trim();
    if (!message || busy) return;
    setEntries((prev) => [...prev, { role: 'user', content: message }]);
    setInput('');
    setBusy(true);
    setError(null);
    try {
      const result = await api.chatWithSetAgent(setId, {
        message,
        history,
      });
      setEntries((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: result.message || 'Applied tool call.',
          toolCalls: result.tool_calls,
          transitionScores: result.affected_transition_scores,
        },
      ]);
      if (result.tool_calls.some((tool) => tool.mutating)) onMutationApplied();
    } catch (err) {
      setError(formatAgentError(err));
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

      {critique && <CritiqueCard critique={critique} persona={persona} />}
      {error && (
        <div className={styles.chatError} role="alert">
          {error}
        </div>
      )}

      <div className={styles.chatScroll} ref={scrollRef}>
        {entries.length === 0 && (
          <div className={styles.chatEmpty}>Ask the agent to critique, explain, or edit the timeline.</div>
        )}
        {entries.map((entry, i) => (
          <div
            key={`${entry.role}-${i}`}
            className={`${styles.chatMessage} ${entry.role === 'user' ? styles.chatUser : styles.chatAgent}`}
          >
            <div className={styles.chatAuthor}>
              {entry.role === 'user'
                ? 'You'
                : persona === 'peer'
                  ? 'WrzDJ Agent'
                  : 'WrzDJSet Assistant'}
            </div>
            <div className={styles.chatBubble}>{entry.content}</div>
            {entry.toolCalls?.map((tool) => <ToolCard key={tool.id} tool={tool} />)}
            {entry.transitionScores && entry.transitionScores.length > 0 && (
              <div className={styles.scoreUpdate}>
                {entry.transitionScores.map((score) => (
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
