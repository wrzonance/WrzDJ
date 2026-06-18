'use client';

import ChatPanelBody, { PersonaToggle } from './ChatPanelBody';
import { useAgentChat } from './useAgentChat';
import styles from '../setbuilder.module.css';

/**
 * Desktop chat shell: occupies the `chat` grid column, toggles between a
 * collapsed spine (showing the critique grade) and the full panel. All chat
 * behavior lives in {@link useAgentChat}; rendering in {@link ChatPanelBody}.
 */
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
  const chat = useAgentChat(setId, { open, refreshToken, onMutationApplied });

  if (!open) {
    return (
      <button className={`${styles.panel} ${styles.chatCollapsed}`} onClick={onToggle}>
        <span className={styles.chatCollapsedLabel}>Agent</span>
        {chat.critique?.overall_grade && (
          <span className={styles.chatCollapsedGrade}>{chat.critique.overall_grade}</span>
        )}
      </button>
    );
  }

  return (
    <section className={`${styles.panel} ${styles.chatSection}`} aria-label="Agent chat">
      <div className={styles.chatHeader}>
        <div className={styles.panelHeaderInline}>Agent</div>
        <PersonaToggle persona={chat.persona} onChange={chat.setPersona} />
        <button className="btn btn-sm" onClick={onToggle}>
          Collapse
        </button>
      </div>
      <ChatPanelBody chat={chat} />
    </section>
  );
}
