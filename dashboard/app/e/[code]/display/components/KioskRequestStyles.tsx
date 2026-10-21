'use client';

export function KioskRequestStyles() {
  return <style jsx global>{`        /* ── Modal styles (used by RequestModal component) ── */
        .modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0,0,0,0.9);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
          padding: 2rem;
        }
        .modal-content {
          background: #1f2937;
          border-radius: 1.5rem;
          padding: 2rem;
          width: 100%;
          max-width: 500px;
          max-height: 80vh;
          overflow-y: auto;
          transition: max-height 0.2s ease, margin-top 0.2s ease;
        }
        .modal-content.keyboard-active {
          max-width: 700px;
          max-height: 95vh;
          overflow-y: auto;
          padding: 1.25rem;
          padding-bottom: 280px;
        }
        .modal-overlay.keyboard-overlay-active {
          align-items: flex-start;
          padding-top: 1rem;
          padding-left: 1rem;
          padding-right: 1rem;
        }
        .modal-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 1.5rem;
        }
        .modal-title {
          font-size: 1.5rem;
          font-weight: bold;
          color: #fff;
          margin: 0;
        }
        .modal-close {
          background: transparent;
          border: none;
          color: var(--text-secondary);
          font-size: 2rem;
          cursor: pointer;
          line-height: 1;
        }
        .search-form {
          display: flex;
          gap: 0.5rem;
          margin-bottom: 1rem;
        }
        .search-feedback {
          margin: 0.5rem 0 1rem;
          text-align: center;
          color: var(--text-secondary);
          font-size: 1rem;
        }
        .search-feedback-error {
          color: #f87171;
        }
        .search-input {
          flex: 1;
          background: #374151;
          border: none;
          border-radius: 0.5rem;
          padding: 1rem;
          color: #fff;
          font-size: 1rem;
        }
        .search-button {
          background: #3b82f6;
          border: none;
          border-radius: 0.5rem;
          padding: 1rem 1.5rem;
          color: #fff;
          font-weight: 500;
          cursor: pointer;
        }
        .search-results {
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
          max-height: 300px;
          overflow-y: auto;
          transition: max-height 0.2s ease;
        }
        .search-results-compact {
          max-height: 50vh;
        }
        .search-result-item {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          background: #374151;
          padding: 0.75rem;
          border-radius: 0.5rem;
          border: none;
          cursor: pointer;
          text-align: left;
          width: 100%;
          color: #fff;
        }
        .search-result-item:hover {
          background: #4b5563;
        }
        .confirm-section {
          text-align: center;
        }
        .confirm-song {
          margin-bottom: 1.5rem;
        }
        .confirm-title {
          font-size: 1.25rem;
          font-weight: bold;
          color: #fff;
          margin: 0 0 0.25rem;
        }
        .confirm-artist {
          color: var(--text-secondary);
          margin: 0;
        }
        .note-input {
          width: 100%;
          background: #374151;
          border: none;
          border-radius: 0.5rem;
          padding: 1rem;
          color: #fff;
          font-size: 1rem;
          margin-bottom: 1rem;
        }
        .confirm-buttons {
          display: flex;
          gap: 1rem;
        }
        .confirm-submit {
          flex: 1;
          background: #22c55e;
          border: none;
          border-radius: 0.5rem;
          padding: 1rem;
          color: #fff;
          font-weight: bold;
          font-size: 1.1rem;
          cursor: pointer;
        }
        .confirm-back {
          background: #374151;
          border: none;
          border-radius: 0.5rem;
          padding: 1rem 1.5rem;
          color: #fff;
          cursor: pointer;
        }
        .success-message {
          text-align: center;
          padding: 2rem;
        }
        .success-icon {
          font-size: 4rem;
          margin-bottom: 1rem;
        }
        .success-text {
          font-size: 1.5rem;
          color: #22c55e;
          font-weight: bold;
        }
        .success-vote-count {
          color: var(--text-secondary);
          margin-top: 0.5rem;
        }
        .search-result-art {
          width: 48px;
          height: 48px;
          border-radius: 4px;
          object-fit: cover;
        }
        .search-result-placeholder {
          width: 48px;
          height: 48px;
          border-radius: 4px;
          background: rgba(255,255,255,0.1);
          display: flex;
          align-items: center;
          justify-content: center;
          color: rgba(255,255,255,0.5);
        }
        .search-result-info {
          flex: 1;
          min-width: 0;
        }
        .search-result-title {
          font-weight: 500;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .search-result-artist {
          color: var(--text-secondary);
          font-size: 0.875rem;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
`}</style>;
}
