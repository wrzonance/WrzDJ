'use client';

import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { Event, PoolImportResult } from '@/lib/api/types';
import sharedStyles from '../../setbuilder-shared.module.css';
import importStyles from '../../setbuilder-import.module.css';
import { SourceIcon, sourceColor } from '../pool/PoolBadges';
import { ModalHeader, errMessage, runImport, type ImportModalProps } from './ImportModalShared';

function appendImportResult(
  aggregate: PoolImportResult | null,
  result: PoolImportResult,
): PoolImportResult {
  if (!aggregate) return result;
  return {
    ...result,
    added: aggregate.added + result.added,
    deduped: aggregate.deduped + result.deduped,
  };
}

export default function ImportEvent({ setId, existingRefs, onClose, onImported, onError, commit }: ImportModalProps) {
  const [events, setEvents] = useState<Event[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);

  const loadEvents = useCallback(() => {
    setLoadError(false);
    setEvents(null);
    api.getEvents().then(setEvents).catch(() => setLoadError(true));
  }, []);

  useEffect(loadEvents, [loadEvents]);

  const togglePicked = (eventId: number) => {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(eventId)) next.delete(eventId);
      else next.add(eventId);
      return next;
    });
  };

  const doImport = async () => {
    const selectedEventIds = (events ?? [])
      .map((event) => event.id)
      .filter((eventId) => picked.has(eventId));
    if (!selectedEventIds.length) return;
    setBusy(true);
    try {
      const outcome = await runImport(commit, 'Import event requests', async () => {
        let aggregate: PoolImportResult | null = null;
        for (const eventId of selectedEventIds) {
          try {
            const result = await api.importPoolEvent(setId, eventId);
            aggregate = appendImportResult(aggregate, result);
          } catch (e) {
            if (!aggregate) throw e;
            return { aggregate, error: e };
          }
        }
        return { aggregate, error: null };
      });
      if (outcome.aggregate) onImported(outcome.aggregate);
      if (outcome.error) {
        onError(errMessage(outcome.error));
      }
    } catch (e) {
      onError(errMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <ModalHeader
        kind="event"
        title="Import event requests"
        subtitle="Tracks that guests requested via WrzDJ."
        onClose={onClose}
      />
      <div className={importStyles.imBody}>
        {events === null && !loadError && <div className={sharedStyles.imEmpty}>Loading events…</div>}
        {loadError && (
          <div className={sharedStyles.imEmpty} role="alert">
            <span>Could not load events.</span>{' '}
            <button type="button" className="btn btn-sm" onClick={loadEvents}>
              Retry
            </button>
          </div>
        )}
        {events !== null && events.length === 0 && (
          <div className={sharedStyles.imEmpty}>No events yet.</div>
        )}
        <div className={importStyles.imList}>
          {(events ?? []).map((e) => {
            const already = existingRefs.has(`event:${e.id}`);
            const checked = picked.has(e.id);
            return (
              <label
                key={e.id}
                className={`${importStyles.imListItem} ${checked ? importStyles.imPicked : ''}`}
                aria-disabled={busy}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => togglePicked(e.id)}
                  disabled={busy}
                  aria-label={`Select ${e.name}`}
                />
                <span style={{ color: sourceColor('event') }}>
                  <SourceIcon kind="event" size={16} />
                </span>
                <span className={importStyles.imListInfo}>
                  <span className={importStyles.imListTitle}>
                    {e.name}
                    {already && <span className={importStyles.imImported}> · already imported</span>}
                  </span>
                  <span className={importStyles.imListSub}>{e.code}</span>
                </span>
              </label>
            );
          })}
        </div>
        <div className={importStyles.imFootnote}>
          Imported tracks are de-duped automatically — tracks already in the pool keep their
          original source tag. Re-importing refreshes new requests only.
        </div>
      </div>
      <div className={importStyles.imFooter}>
        <button className="btn btn-sm" onClick={onClose}>
          Cancel
        </button>
        <span style={{ flex: 1 }} />
        <button
          className="btn btn-primary btn-sm"
          disabled={!picked.size || busy}
          onClick={doImport}
        >
          {busy ? 'Importing…' : 'Import requests'}
        </button>
      </div>
    </>
  );
}
