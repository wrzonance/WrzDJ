'use client';

import { useEffect, useState } from 'react';
import { api, ApiError, Event, TidalStatus, TidalSearchResult, BeatportStatus } from '@/lib/api';
import type { BeatportSearchResult, SongRequest } from '@/lib/api/types';

const TIDAL_AUTH_POLL_INTERVAL_MS = 2_000;
const TIDAL_AUTH_TIMEOUT_MS = 10 * 60 * 1_000;

interface EventProviderSyncOptions {
  event: Event | null;
  requests: SongRequest[];
  setAllRequests: React.Dispatch<React.SetStateAction<SongRequest[]>>;
  refetchRequests: () => void;
  setActionError: (message: string | null) => void;
}

export function useEventProviderSync({ event, requests, setAllRequests, refetchRequests, setActionError }: EventProviderSyncOptions) {
  // Tidal sync state
  const [tidalStatus, setTidalStatus] = useState<TidalStatus | null>(null);
  const [tidalSyncEnabled, setTidalSyncEnabled] = useState(false);
  const [togglingTidalSync, setTogglingTidalSync] = useState(false);
  const [syncingRequest, setSyncingRequest] = useState<number | null>(null);
  const [showTidalPicker, setShowTidalPicker] = useState<number | null>(null);
  const [tidalSearchQuery, setTidalSearchQuery] = useState('');
  const [tidalSearchResults, setTidalSearchResults] = useState<TidalSearchResult[]>([]);
  const [searchingTidal, setSearchingTidal] = useState(false);
  const [linkingTrack, setLinkingTrack] = useState(false);

  // Beatport sync state
  const [beatportStatus, setBeatportStatus] = useState<BeatportStatus | null>(null);
  const [beatportSyncEnabled, setBeatportSyncEnabled] = useState(false);
  const [togglingBeatportSync, setTogglingBeatportSync] = useState(false);
  const [showBeatportPicker, setShowBeatportPicker] = useState<number | null>(null);
  const [beatportSearchQuery, setBeatportSearchQuery] = useState('');
  const [beatportSearchResults, setBeatportSearchResults] = useState<BeatportSearchResult[]>([]);
  const [searchingBeatport, setSearchingBeatport] = useState(false);
  const [linkingBeatportTrack, setLinkingBeatportTrack] = useState(false);

  const [syncReportExpanded, setSyncReportExpanded] = useState(false);
  const [focusedSyncRequestId, setFocusedSyncRequestId] = useState<number | null>(null);
    // Tidal device login state
  const [showTidalLogin, setShowTidalLogin] = useState(false);
  const [tidalLoginUrl, setTidalLoginUrl] = useState('');
  const [tidalLoginCode, setTidalLoginCode] = useState('');
  const [tidalLoginPolling, setTidalLoginPolling] = useState(false);

  // Beatport login modal state
  const [showBeatportLogin, setShowBeatportLogin] = useState(false);

  // Tidal auth polling — driven by tidalLoginPolling state with proper cleanup
  useEffect(() => {
    if (!tidalLoginPolling) return;

    const pollInterval = setInterval(async () => {
      try {
        const result = await api.checkTidalAuth();
        if (result.complete) {
          setTidalLoginPolling(false);
          setShowTidalLogin(false);
          setTidalStatus({ linked: true, user_id: result.user_id || null, expires_at: null, integration_enabled: true });
        } else if (result.error) {
          setTidalLoginPolling(false);
          setActionError(`Tidal login failed: ${result.error}`);
        }
      } catch {
        // Transient error — keep polling
      }
    }, TIDAL_AUTH_POLL_INTERVAL_MS);

    // Stop polling after 10 minutes
    const timeout = setTimeout(() => {
      setTidalLoginPolling(false);
    }, TIDAL_AUTH_TIMEOUT_MS);

    return () => {
      clearInterval(pollInterval);
      clearTimeout(timeout);
    };
  }, [tidalLoginPolling]);

  const handleToggleTidalSync = async () => {
    if (!event) return;
    setTogglingTidalSync(true);
    try {
      const newEnabled = !tidalSyncEnabled;
      await api.updateTidalEventSettings(event.id, { tidal_sync_enabled: newEnabled });
      setTidalSyncEnabled(newEnabled);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to toggle Tidal sync');
    } finally {
      setTogglingTidalSync(false);
    }
  };

  const handleConnectTidal = async () => {
    try {
      const { verification_url, user_code } = await api.startTidalAuth();
      setTidalLoginUrl(verification_url);
      setTidalLoginCode(user_code);
      setShowTidalLogin(true);
      setTidalLoginPolling(true);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to start Tidal auth');
    }
  };

  const handleCancelTidalLogin = async () => {
    try {
      await api.cancelTidalAuth();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to cancel Tidal auth');
    }
    setShowTidalLogin(false);
    setTidalLoginPolling(false);
  };

  const handleDisconnectTidal = async () => {
    try {
      await api.disconnectTidal();
      setTidalStatus({ linked: false, user_id: null, expires_at: null, integration_enabled: true });
      setTidalSyncEnabled(false);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to disconnect Tidal');
    }
  };

  const handleSyncToTidal = async (requestId: number) => {
    setSyncingRequest(requestId);
    try {
      const _result = await api.syncRequestToTidal(requestId);
      setAllRequests((prev) =>
        prev.map((r) =>
          r.id === requestId
            ? { ...r }
            : r
        )
      );
      // Refresh to get updated sync_results_json from server
      refetchRequests();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to sync to Tidal');
    } finally {
      setSyncingRequest(null);
    }
  };

  const handleOpenTidalPicker = (requestId: number) => {
    const request = requests.find((r) => r.id === requestId);
    if (request) {
      setTidalSearchQuery(`${request.artist} ${request.song_title}`);
      setShowTidalPicker(requestId);
      setTidalSearchResults([]);
    }
  };

  const handleSearchTidal = async () => {
    if (!tidalSearchQuery.trim()) return;
    setSearchingTidal(true);
    try {
      const results = await api.searchTidal(tidalSearchQuery);
      setTidalSearchResults(results);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to search Tidal');
    } finally {
      setSearchingTidal(false);
    }
  };

  const handleLinkTidalTrack = async (requestId: number, tidalTrackId: string) => {
    setLinkingTrack(true);
    try {
      await api.linkTidalTrack(requestId, tidalTrackId);
      refetchRequests();
      setShowTidalPicker(null);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to link Tidal track');
    } finally {
      setLinkingTrack(false);
    }
  };

  const handleOpenBeatportPicker = (requestId: number) => {
    const request = requests.find((r) => r.id === requestId);
    if (request) {
      setBeatportSearchQuery(`${request.artist} ${request.song_title}`);
      setShowBeatportPicker(requestId);
      setBeatportSearchResults([]);
    }
  };

  const handleSearchBeatport = async () => {
    if (!beatportSearchQuery.trim()) return;
    setSearchingBeatport(true);
    try {
      const results = await api.searchBeatport(beatportSearchQuery);
      setBeatportSearchResults(results);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to search Beatport');
    } finally {
      setSearchingBeatport(false);
    }
  };

  const handleLinkBeatportTrack = async (requestId: number, beatportTrackId: string) => {
    setLinkingBeatportTrack(true);
    try {
      await api.linkBeatportTrack(requestId, beatportTrackId);
      // Reload requests to get updated sync_results_json
      refetchRequests();
      setShowBeatportPicker(null);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to link Beatport track');
    } finally {
      setLinkingBeatportTrack(false);
    }
  };

  // Beatport handlers
  const handleToggleBeatportSync = async () => {
    if (!event) return;
    setTogglingBeatportSync(true);
    try {
      const newEnabled = !beatportSyncEnabled;
      await api.updateBeatportEventSettings(event.id, { beatport_sync_enabled: newEnabled });
      setBeatportSyncEnabled(newEnabled);
    } catch {
      setActionError('Failed to toggle Beatport sync');
    } finally {
      setTogglingBeatportSync(false);
    }
  };

  const handleConnectBeatport = () => {
    setShowBeatportLogin(true);
  };

  const handleBeatportLogin = async (username: string, password: string) => {
    await api.loginBeatport(username, password);
    // Refetch status to get subscription info
    const status = await api.getBeatportStatus().catch(() => ({ linked: true, expires_at: null, configured: true, subscription: null, integration_enabled: true }));
    setBeatportStatus(status);
    setShowBeatportLogin(false);
  };

  const handleDisconnectBeatport = async () => {
    try {
      await api.disconnectBeatport();
      setBeatportStatus({ linked: false, expires_at: null, configured: true, subscription: null, integration_enabled: true });
      setBeatportSyncEnabled(false);
    } catch {
      setActionError('Failed to disconnect Beatport');
    }
  };

  const handleScrollToSyncReport = (requestId: number) => {
    setFocusedSyncRequestId(requestId);
    setSyncReportExpanded(true);
    // Scroll to sync report panel after a tick so it renders expanded
    setTimeout(() => {
      const panel = document.getElementById('sync-report-panel');
      if (panel) {
        panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }, 50);
  };

  return {
    setTidalStatus, setTidalSyncEnabled, setBeatportStatus, setBeatportSyncEnabled,
    tidalStatus, tidalSyncEnabled, togglingTidalSync, syncingRequest, showTidalPicker, setShowTidalPicker,
    tidalSearchQuery, setTidalSearchQuery, tidalSearchResults, searchingTidal, linkingTrack,
    beatportStatus, beatportSyncEnabled, togglingBeatportSync, showBeatportPicker, setShowBeatportPicker,
    beatportSearchQuery, setBeatportSearchQuery, beatportSearchResults, searchingBeatport,
    linkingBeatportTrack, syncReportExpanded, setSyncReportExpanded,
    focusedSyncRequestId, setFocusedSyncRequestId, showTidalLogin, setShowTidalLogin,
    tidalLoginUrl, tidalLoginCode, tidalLoginPolling, showBeatportLogin, setShowBeatportLogin,
    handleToggleTidalSync, handleConnectTidal, handleCancelTidalLogin, handleDisconnectTidal,
    handleSyncToTidal, handleOpenTidalPicker, handleSearchTidal, handleLinkTidalTrack,
    handleOpenBeatportPicker, handleSearchBeatport, handleLinkBeatportTrack,
    handleToggleBeatportSync, handleConnectBeatport, handleBeatportLogin,
    handleDisconnectBeatport, handleScrollToSyncReport,
  };
}
