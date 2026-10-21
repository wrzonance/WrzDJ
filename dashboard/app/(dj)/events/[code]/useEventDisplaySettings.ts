'use client';

import { useState } from 'react';
import { api, ApiError, Event } from '@/lib/api';
import {
  DEFAULT_AUTO_HIDE_MINUTES,
  MAX_AUTO_HIDE_MINUTES,
  MIN_AUTO_HIDE_MINUTES,
} from './eventDisplaySettings';

interface EventDisplaySettingsOptions {
  code: string;
  event: Event | null;
  setEvent: React.Dispatch<React.SetStateAction<Event | null>>;
  setActionError: (message: string | null) => void;
}

export function useEventDisplaySettings({ code, event, setEvent, setActionError }: EventDisplaySettingsOptions) {
  // Now playing visibility toggle
  const [nowPlayingHidden, setNowPlayingHidden] = useState(false);
  const [togglingNowPlaying, setTogglingNowPlaying] = useState(false);
  const [autoHideMinutes, setAutoHideMinutes] = useState(DEFAULT_AUTO_HIDE_MINUTES);
  const [autoHideInput, setAutoHideInput] = useState(String(DEFAULT_AUTO_HIDE_MINUTES));
  const [savingAutoHide, setSavingAutoHide] = useState(false);

  // Requests open/closed toggle
  const [requestsOpen, setRequestsOpen] = useState(true);
  const [togglingRequests, setTogglingRequests] = useState(false);

  // Kiosk display-only mode
  const [kioskDisplayOnly, setKioskDisplayOnly] = useState(false);
  const [togglingDisplayOnly, setTogglingDisplayOnly] = useState(false);

  // Frictionless join (per-event)
  const [frictionlessJoin, setFrictionlessJoin] = useState(false);
  const [togglingFrictionless, setTogglingFrictionless] = useState(false);

  const handleToggleNowPlaying = async () => {
    setTogglingNowPlaying(true);
    try {
      const newHidden = !nowPlayingHidden;
      await api.setNowPlayingVisibility(code, newHidden);
      setNowPlayingHidden(newHidden);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to toggle now playing');
    } finally {
      setTogglingNowPlaying(false);
    }
  };

  const handleSaveAutoHide = async () => {
    const value = parseInt(autoHideInput, 10);
    if (isNaN(value) || value < MIN_AUTO_HIDE_MINUTES || value > MAX_AUTO_HIDE_MINUTES) return;
    setSavingAutoHide(true);
    try {
      const result = await api.setAutoHideMinutes(code, value);
      setAutoHideMinutes(result.now_playing_auto_hide_minutes);
      setAutoHideInput(String(result.now_playing_auto_hide_minutes));
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to update auto-hide timeout');
    } finally {
      setSavingAutoHide(false);
    }
  };

  const handleToggleRequests = async () => {
    setTogglingRequests(true);
    try {
      const newOpen = !requestsOpen;
      await api.setRequestsOpen(code, newOpen);
      setRequestsOpen(newOpen);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to update request availability');
    } finally {
      setTogglingRequests(false);
    }
  };

  const handleToggleDisplayOnly = async () => {
    setTogglingDisplayOnly(true);
    try {
      const newValue = !kioskDisplayOnly;
      await api.setKioskDisplayOnly(code, newValue);
      setKioskDisplayOnly(newValue);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to update kiosk display mode');
    } finally {
      setTogglingDisplayOnly(false);
    }
  };

  const handleToggleFrictionless = async () => {
    if (!event) return;
    setTogglingFrictionless(true);
    try {
      const updated = await api.updateEvent(event.code, { frictionless_join: !frictionlessJoin });
      setFrictionlessJoin(updated.frictionless_join);
      setEvent(updated);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to update frictionless join');
    } finally {
      setTogglingFrictionless(false);
    }
  };

  return {
    nowPlayingHidden, togglingNowPlaying, autoHideMinutes, autoHideInput, setAutoHideInput,
    savingAutoHide, requestsOpen, togglingRequests, kioskDisplayOnly, frictionlessJoin,
    togglingFrictionless, togglingDisplayOnly, setFrictionlessJoin, setNowPlayingHidden, setRequestsOpen, setKioskDisplayOnly,
    setAutoHideMinutes, handleToggleNowPlaying, handleSaveAutoHide, handleToggleRequests,
    handleToggleDisplayOnly, handleToggleFrictionless,
  };
}
