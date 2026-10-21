'use client';

import ChatPanelBody, { PersonaToggle } from './ChatPanelBody';
import { useAgentChat } from './useAgentChat';
import type { BuilderCommit } from '../useSetDocumentHistory';
import styles from '../../setbuilder.module.css';
import chatStyles from '../../setbuilder-chat.module.css';

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
  commit,
}: {
  setId: number;
  open: boolean;
  onToggle: () => void;
  refreshToken?: number;
  onMutationApplied: () => void;
  commit?: BuilderCommit;
}) {
  const chat = useAgentChat(setId, { open, refreshToken, onMutationApplied, commit });

  if (!open) {
    return (
      <button className={`${styles.panel} ${chatStyles.chatCollapsed}`} onClick={onToggle}>
        <span className={chatStyles.chatCollapsedLabel}>Agent</span>
        {chat.critique?.overall_grade && (
          <span className={chatStyles.chatCollapsedGrade}>{chat.critique.overall_grade}</span>
        )}
      </button>
    );
  }

  return (
    <section className={`${styles.panel} ${chatStyles.chatSection}`} aria-label="Agent chat">
      <div className={chatStyles.chatHeader}>
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
