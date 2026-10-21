'use client';

import { useState } from 'react';
import type { LlmConnector, LlmConnectorType } from '@/lib/api/types';
import { CONNECTOR_TYPE_LABELS } from './ProviderCreationSection';

const STATUS_LABELS: Record<string, { text: string; color: string }> = {
  active: { text: 'Active', color: 'var(--color-success)' },
  auth_invalid: { text: 'Auth invalid', color: 'var(--color-danger)' },
  disabled: { text: 'Disabled', color: 'var(--text-secondary)' },
};

interface AiProviderConnectorCardProps {
  connector: LlmConnector;
  streaming: boolean;
  isStreaming: boolean;
  onTest: (id: number) => Promise<string>;
  onStreamTest: (id: number, onTextDelta: (text: string) => void) => Promise<void>;
  onDelete: (id: number) => void;
  onSetDefault: (id: number) => void;
  onUnsetDefault: (id: number) => void;
}

export function AiProviderConnectorCard({
  connector,
  streaming,
  isStreaming,
  onTest,
  onStreamTest,
  onDelete,
  onSetDefault,
  onUnsetDefault,
}: AiProviderConnectorCardProps) {
  const [testState, setTestState] = useState('');
  const [streamText, setStreamText] = useState<string | null>(null);
  const status = STATUS_LABELS[connector.status] ?? {
    text: connector.status,
    color: 'var(--text-secondary)',
  };
  const canPin = connector.status === 'active';
  const radioId = `connector-default-${connector.id}`;

  const handleTest = async () => {
    setTestState('Testing…');
    try {
      setTestState(await onTest(connector.id));
    } catch (error) {
      setTestState(error instanceof Error ? error.message : 'Test failed');
    }
  };

  const handleStreamTest = async () => {
    setStreamText('');
    try {
      await onStreamTest(connector.id, (text) => {
        setStreamText((current) => (current ?? '') + text);
      });
    } catch (error) {
      setStreamText(
        error instanceof Error ? `(stream test failed: ${error.message})` : '(stream test failed)',
      );
    }
  };

  return (
    <div className="card" style={{ marginTop: '1rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
            <div style={{ fontWeight: 600 }}>{connector.display_name}</div>
            {connector.is_default && (
              <span
                style={{
                  fontSize: '0.7rem',
                  padding: '0.125rem 0.5rem',
                  borderRadius: '0.5rem',
                  background: 'var(--color-success)',
                  color: 'var(--text-on-bright-accent)',
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}
              >
                Default
              </span>
            )}
          </div>
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
            {CONNECTOR_TYPE_LABELS[connector.connector_type as LlmConnectorType] ?? connector.connector_type}
            {connector.model_hint ? ` · ${connector.model_hint}` : ''}
            {connector.base_url_plain ? ` · ${connector.base_url_plain}` : ''}
          </div>
          <div style={{ marginTop: '0.5rem', fontSize: '0.875rem', color: status.color, fontWeight: 600 }}>
            {status.text}
            {testState ? ` · ${testState}` : ''}
          </div>
          <label
            htmlFor={radioId}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
              marginTop: '0.5rem',
              fontSize: '0.85rem',
              color: canPin ? 'var(--text)' : 'var(--text-secondary)',
              cursor: canPin ? 'pointer' : 'not-allowed',
            }}
          >
            <input
              id={radioId}
              type="radio"
              name="llm-connector-default"
              checked={connector.is_default}
              disabled={!canPin && !connector.is_default}
              onChange={() => {
                if (canPin) onSetDefault(connector.id);
              }}
            />
            {connector.is_default ? (
              <>
                Pinned as default ·{' '}
                <button
                  type="button"
                  className="btn-link"
                  onClick={(event) => {
                    event.preventDefault();
                    onUnsetDefault(connector.id);
                  }}
                  style={{
                    background: 'none',
                    border: 'none',
                    padding: 0,
                    color: 'var(--text-secondary)',
                    textDecoration: 'underline',
                    cursor: 'pointer',
                    font: 'inherit',
                  }}
                >
                  Unpin
                </button>
              </>
            ) : (
              <span>Set as default</span>
            )}
          </label>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          <button className="btn btn-secondary" onClick={handleTest}>Test</button>
          <button
            className="btn btn-secondary"
            onClick={handleStreamTest}
            disabled={streaming}
          >
            {isStreaming ? 'Streaming…' : 'Stream test'}
          </button>
          <button className="btn btn-danger" onClick={() => onDelete(connector.id)}>
            Delete
          </button>
        </div>
        {streamText && (
          <div
            style={{
              marginTop: '0.5rem',
              fontSize: '0.875rem',
              color: 'var(--text-secondary)',
              fontStyle: 'italic',
            }}
          >
            {streamText}
          </div>
        )}
      </div>
    </div>
  );
}
