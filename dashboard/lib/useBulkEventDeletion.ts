'use client';

import { useCallback, useState } from 'react';
import { toggleSetContents, toggleSetValue } from '@/lib/set-toggle';

interface UseBulkEventDeletionOptions {
  deleteEvents: (eventCodes: string[]) => Promise<unknown>;
  refreshEvents: () => void | Promise<void>;
  onError: (message: string) => void;
  fallbackErrorMessage?: string;
}

export function useBulkEventDeletion({
  deleteEvents,
  refreshEvents,
  onError,
  fallbackErrorMessage = 'Failed to delete events',
}: UseBulkEventDeletionOptions) {
  const [selectedEvents, setSelectedEvents] = useState<Set<string>>(new Set());
  const [deletingSelected, setDeletingSelected] = useState(false);

  const toggleEvent = useCallback((eventCode: string) => {
    setSelectedEvents((previous) => toggleSetValue(previous, eventCode));
  }, []);

  const toggleEvents = useCallback((eventCodes: string[]) => {
    setSelectedEvents((previous) => toggleSetContents(previous, eventCodes));
  }, []);

  const clearSelection = useCallback(() => setSelectedEvents(new Set()), []);

  const deleteSelected = useCallback(async () => {
    if (selectedEvents.size === 0) return;
    if (!window.confirm(`Delete ${selectedEvents.size} event${selectedEvents.size === 1 ? '' : 's'}? This cannot be undone.`)) return;

    setDeletingSelected(true);
    try {
      await deleteEvents([...selectedEvents]);
      clearSelection();
      await refreshEvents();
    } catch (error) {
      onError(error instanceof Error ? error.message : fallbackErrorMessage);
    } finally {
      setDeletingSelected(false);
    }
  }, [deleteEvents, fallbackErrorMessage, onError, refreshEvents, selectedEvents]);

  return {
    selectedEvents,
    deletingSelected,
    toggleEvent,
    toggleEvents,
    clearSelection,
    deleteSelected,
  };
}
