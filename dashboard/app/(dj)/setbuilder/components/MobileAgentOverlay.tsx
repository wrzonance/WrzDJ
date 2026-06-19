'use client';

import { useEffect, useRef, useState } from 'react';
import ChatPanelBody, { PersonaToggle } from './ChatPanelBody';
import { useAgentChat } from './useAgentChat';
import type { BuilderCommit } from './useSetDocumentHistory';
import styles from '../setbuilder.module.css';

/**
 * Mobile agent surface: a floating "Agent" FAB (carrying the critique grade)
 * that opens a full-viewport overlay with the complete chat experience. Shares
 * {@link useAgentChat}/{@link ChatPanelBody} with the desktop sidebar; history
 * loads only while the overlay is open. Rendered instead of (never alongside)
 * the desktop sidebar on narrow viewports.
 */
export default function MobileAgentOverlay({
  setId,
  refreshToken = 0,
  onMutationApplied,
  commit,
}: {
  setId: number;
  refreshToken?: number;
  onMutationApplied: () => void;
  commit?: BuilderCommit;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const wasOpenRef = useRef(false);
  const chat = useAgentChat(setId, { open, refreshToken, onMutationApplied, commit });
  const grade = chat.critique?.overall_grade;

  // Dialog focus lifecycle: move focus into the overlay on open, close on Escape,
  // and restore focus to the FAB that opened it when it closes.
  useEffect(() => {
    if (open) {
      wasOpenRef.current = true;
      closeRef.current?.focus();
      const onKeyDown = (event: KeyboardEvent) => {
        if (event.key === 'Escape') setOpen(false);
      };
      window.addEventListener('keydown', onKeyDown);
      return () => window.removeEventListener('keydown', onKeyDown);
    }
    if (wasOpenRef.current) {
      wasOpenRef.current = false;
      triggerRef.current?.focus();
    }
  }, [open]);

  if (!open) {
    return (
      <button
        ref={triggerRef}
        className={styles.agentFab}
        aria-label="Open agent chat"
        onClick={() => setOpen(true)}
      >
        <span className={styles.agentFabLabel}>Agent</span>
        {grade && (
          <span className={styles.agentFabGrade} data-testid="agent-fab-grade">
            {grade}
          </span>
        )}
      </button>
    );
  }

  return (
    <div className={styles.agentOverlay} role="dialog" aria-modal="true" aria-label="Agent chat">
      <div className={styles.agentOverlayHeader}>
        <button
          ref={closeRef}
          className={styles.agentOverlayBack}
          aria-label="Close agent chat"
          onClick={() => setOpen(false)}
        >
          <span aria-hidden="true">←</span>
        </button>
        <div className={styles.panelHeaderInline}>Agent</div>
        {grade && <span className={styles.chatCollapsedGrade}>{grade}</span>}
        <PersonaToggle persona={chat.persona} onChange={chat.setPersona} />
      </div>
      <ChatPanelBody chat={chat} />
    </div>
  );
}
