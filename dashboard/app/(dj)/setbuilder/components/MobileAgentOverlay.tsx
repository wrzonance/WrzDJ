'use client';

import { useState } from 'react';
import ChatPanelBody, { PersonaToggle } from './ChatPanelBody';
import { useAgentChat } from './useAgentChat';
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
}: {
  setId: number;
  refreshToken?: number;
  onMutationApplied: () => void;
}) {
  const [open, setOpen] = useState(false);
  const chat = useAgentChat(setId, { open, refreshToken, onMutationApplied });
  const grade = chat.critique?.overall_grade;

  if (!open) {
    return (
      <button className={styles.agentFab} aria-label="Open agent chat" onClick={() => setOpen(true)}>
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
