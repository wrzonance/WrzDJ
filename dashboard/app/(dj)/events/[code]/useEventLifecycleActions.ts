'use client';

import { useState } from 'react';
import { api, ApiError, type ArchivedEvent, type Event } from '@/lib/api';

interface EventLifecycleOptions {
  code: string;
  event: Event | ArchivedEvent | null;
  setEvent: React.Dispatch<React.SetStateAction<Event | ArchivedEvent | null>>;
  router: { push: (href: string) => void };
  setActionError: (message: string | null) => void;
}

function toLocalDateTimeString(date: Date): string {
  const pad = (value: number) => value.toString().padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function useEventLifecycleActions({ code, event, setEvent, router, setActionError }: EventLifecycleOptions) {
  const [editingExpiry, setEditingExpiry] = useState(false);
  const [newExpiryDate, setNewExpiryDate] = useState('');
  const [updatingExpiry, setUpdatingExpiry] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const handleEditExpiry = () => {
    if (!event) return;
    setNewExpiryDate(toLocalDateTimeString(new Date(event.expires_at)));
    setEditingExpiry(true);
  };

  const handleSaveExpiry = async () => {
    if (!newExpiryDate) return;
    setUpdatingExpiry(true);
    try {
      const updated = await api.updateEvent(code, { expires_at: new Date(newExpiryDate).toISOString() });
      setEvent(updated);
      setEditingExpiry(false);
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'Failed to update expiry');
    } finally {
      setUpdatingExpiry(false);
    }
  };

  const handleDeleteEvent = async () => {
    setDeleting(true);
    try {
      await api.deleteEvent(code);
      router.push('/dashboard');
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'Failed to delete event');
      setDeleting(false);
      setShowDeleteConfirm(false);
    }
  };

  return {
    editingExpiry, newExpiryDate, updatingExpiry, showDeleteConfirm, deleting,
    setEditingExpiry, setNewExpiryDate, setShowDeleteConfirm,
    handleEditExpiry, handleSaveExpiry, handleDeleteEvent,
  };
}
