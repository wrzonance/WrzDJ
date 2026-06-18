'use client';

import { useEffect, useRef } from 'react';
import type { AppliedToolCall, SetCritique, TransitionScore } from '@/lib/api-types';
import type { AgentChatController, Persona } from './useAgentChat';
import styles from '../setbuilder.module.css';

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

function critiqueFlags(tool: AppliedToolCall): { type: string; slotPosition: number | null }[] {
  if (tool.name !== 'critique_set') return [];
  const result = tool.result;
  if (!result || typeof result !== 'object') return [];
  const flags = (result as Record<string, unknown>).flags;
  if (!Array.isArray(flags)) return [];
  return flags
    .map((item) => {
      if (!item || typeof item !== 'object' || !('type' in item)) return null;
      const data = item as Record<string, unknown>;
      const type = typeof data.type === 'string' ? data.type : '';
      if (!type) return null;
      const slotPosition = typeof data.slot_position === 'number' ? data.slot_position : null;
      return { type, slotPosition };
    })
    .filter((flag): flag is { type: string; slotPosition: number | null } => Boolean(flag));
}

export function PersonaToggle({
  persona,
  onChange,
}: {
  persona: Persona;
  onChange: (persona: Persona) => void;
}) {
  return (
    <div className={styles.personaToggle} aria-label="Agent personality">
      <button
        className={persona === 'peer' ? styles.personaActive : ''}
        onClick={() => onChange('peer')}
      >
        Peer
      </button>
      <button
        className={persona === 'pro' ? styles.personaActive : ''}
        onClick={() => onChange('pro')}
      >
        Pro
      </button>
    </div>
  );
}

function ToolCard({ tool }: { tool: AppliedToolCall }) {
  const toolName = tool.name.replaceAll('_', ' ');
  const rationale = tool.rationale?.trim() ?? '';
  const summary = tool.display_summary?.trim() || rationale || toolName;
  const skippedLocks = lockSkipReasons(tool);
  const flags = critiqueFlags(tool);
  return (
    <div className={styles.toolCallCard} data-testid="agent-tool-card">
      <span className={styles.toolName}>{toolName}</span>
      <div className={styles.toolBody}>
        <div className={styles.toolSummary}>{summary}</div>
        {rationale && rationale !== summary && (
          <div className={styles.toolRationale}>{rationale}</div>
        )}
        {skippedLocks.map((reason) => (
          <div key={reason} className={styles.toolRationale} data-testid="agent-lock-skip">
            {reason}
          </div>
        ))}
        {flags.length > 0 && (
          <div className={styles.critiqueFlags}>
            {flags.map((flag, i) => (
              <span
                key={`${flag.type}-${i}`}
                className={`${styles.flagChip} ${flagTone(flag.type)}`}
              >
                {formatFlag(flag.type)}
                {flag.slotPosition != null ? ` · ${flag.slotPosition + 1}` : ''}
              </span>
            ))}
          </div>
        )}
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

/**
 * Presentational chat body shared by the desktop sidebar and mobile overlay.
 * Renders context meta, the critique card, errors, the scrolling message list
 * (with tool cards and transition-score chips), and the composer. All state and
 * actions come from {@link AgentChatController}.
 */
export default function ChatPanelBody({ chat }: { chat: AgentChatController }) {
  const { persona, critique, entries, historyMeta, input, setInput, busy, error, suggestions } =
    chat;
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [entries, busy]);

  return (
    <>
      {historyMeta && (
        <div className={styles.chatContextMeta}>
          {historyMeta.usesCompactContext
            ? `Uses compact context + last ${historyMeta.recentTurnLimit} turns`
            : 'Uses recent turns'}
        </div>
      )}
      {critique && <CritiqueCard critique={critique} persona={persona} />}
      {error && (
        <div className={styles.chatError} role="alert">
          {error}
        </div>
      )}

      <div className={styles.chatScroll} ref={scrollRef}>
        {entries.length === 0 && (
          <div className={styles.chatEmpty}>
            Ask the agent to critique, explain, or edit the timeline.
          </div>
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
            <button
              key={suggestion}
              className={styles.suggestionChip}
              onClick={() => chat.send(suggestion)}
            >
              {suggestion}
            </button>
          ))}
        </div>
        <div className={styles.chatInputWrap}>
          <textarea
            className={styles.chatInput}
            value={input}
            placeholder={
              persona === 'peer' ? 'tell the agent what to fix...' : 'Issue an instruction...'
            }
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                chat.send();
              }
            }}
            rows={1}
          />
          <button
            className={styles.chatSend}
            disabled={!input.trim() || busy}
            onClick={() => chat.send()}
          >
            Send
          </button>
        </div>
      </div>
    </>
  );
}
