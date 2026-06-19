'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useRouter, useParams } from 'next/navigation';
import Link from 'next/link';
import { QRCodeSVG } from 'qrcode.react';
import { useAuth } from '@/lib/auth';
import { api, ApiError, Event, ArchivedEvent, SongRequest, PlayHistoryItem, TidalStatus, TidalSearchResult, BeatportStatus, CollectionSettingsResponse, PUBLIC_PAGE_MAX } from '@/lib/api';
import { useEventStream } from '@/lib/use-event-stream';
import { usePollingLoop } from '@/lib/usePollingLoop';
import type { BeatportSearchResult, NowPlayingInfo, RequestSort, SortDirection } from '@/lib/api-types';
import { SORT_FIELD_DEFAULT_DIRECTION, isRequestSort, migrateLegacySort } from '@/lib/request-sort';
import { useHelp } from '@/lib/help/HelpContext';
import { HelpSpot } from '@/components/help/HelpSpot';
import { HelpButton } from '@/components/help/HelpButton';
import { OnboardingOverlay } from '@/components/help/OnboardingOverlay';
import { useTabTitle } from '@/lib/tab-title';
import { EventErrorCard } from '@/components/EventErrorCard';
import { DeleteEventModal } from './components/DeleteEventModal';
import { NowPlayingBadge } from './components/NowPlayingBadge';
import { TidalLoginModal } from './components/TidalLoginModal';
import { BeatportLoginModal } from './components/BeatportLoginModal';
import { ServiceTrackPickerModal } from './components/ServiceTrackPickerModal';
import { RequestQueueSection } from './components/RequestQueueSection';
import type { StatusFilter } from './components/types';
import { PlayHistorySection } from './components/PlayHistorySection';
import { SongManagementTab } from './components/SongManagementTab';
import { EventManagementTab } from './components/EventManagementTab';
import PreEventVotingTab from './components/PreEventVotingTab';
import type { RecommendedTrack } from '@/lib/api-types';

function toLocalDateTimeString(date: Date): string {
  const pad = (n: number) => n.toString().padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Coerce the server's open `status_counts` dict into the strict per-tab shape,
 *  defaulting any absent status to 0 (issue #478). The backend always returns
 *  all six keys, but this keeps the type honest at the boundary. */
function normalizeStatusCounts(
  counts: Record<string, number> | null | undefined,
): Record<StatusFilter, number> {
  const c = counts ?? {};
  return {
    all: c.all ?? 0,
    new: c.new ?? 0,
    accepted: c.accepted ?? 0,
    playing: c.playing ?? 0,
    played: c.played ?? 0,
    rejected: c.rejected ?? 0,
  };
}

/** Read the persisted sort field for an event, falling back to the legacy
 *  toggle then the default. Returns a valid {@link RequestSort}. */
function readStoredSortField(code: string): RequestSort {
  try {
    const storedField = localStorage.getItem(`wrzdj-sortfield-${code}`);
    if (storedField && isRequestSort(storedField)) return storedField;
    return migrateLegacySort(localStorage.getItem(`wrzdj-sort-${code}`));
  } catch {
    return migrateLegacySort(null);
  }
}

export default function EventQueuePage() {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();
  const params = useParams();
  const code = params.code as string;

  const [event, setEvent] = useState<Event | ArchivedEvent | null>(null);
  const [requests, setRequests] = useState<SongRequest[]>([]);
  // Growing-window pagination (issue #478): every refresh re-fetches
  // [0, displayLimit) so live vote/status changes never drift the offset.
  const INITIAL_DISPLAY_LIMIT = 100;
  const [displayLimit, setDisplayLimit] = useState(INITIAL_DISPLAY_LIMIT);
  const [requestTotal, setRequestTotal] = useState(0);
  // Status filtering is server-side (issue #478): the active filter is lifted
  // here so the 5s poll AND manual reloads fetch with it, and the tab counts
  // come from the server's true per-status totals (not the loaded window).
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [statusCounts, setStatusCounts] = useState<Record<StatusFilter, number>>({
    all: 0, new: 0, accepted: 0, playing: 0, played: 0, rejected: 0,
  });
  const [playHistory, setPlayHistory] = useState<PlayHistoryItem[]>([]);
  const [playHistoryTotal, setPlayHistoryTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState<number | null>(null);
  const [acceptingAll, setAcceptingAll] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportingHistory, setExportingHistory] = useState(false);

  const [eventStatus, setEventStatus] = useState<'active' | 'expired' | 'archived'>('active');
  const [error, setError] = useState<{ message: string; status: number } | null>(null);

  const [editingExpiry, setEditingExpiry] = useState(false);
  const [newExpiryDate, setNewExpiryDate] = useState('');
  const [updatingExpiry, setUpdatingExpiry] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Now playing visibility toggle
  const [nowPlayingHidden, setNowPlayingHidden] = useState(false);
  const [togglingNowPlaying, setTogglingNowPlaying] = useState(false);
  const [autoHideMinutes, setAutoHideMinutes] = useState(10);
  const [autoHideInput, setAutoHideInput] = useState('10');
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

  // Bridge / now-playing state
  const [bridgeConnected, setBridgeConnected] = useState(false);
  const [nowPlaying, setNowPlaying] = useState<NowPlayingInfo | null>(null);
  const [bridgeDetails, setBridgeDetails] = useState<{
    circuitBreakerState: string | null;
    bufferSize: number | null;
    pluginId: string | null;
    deckCount: number | null;
    uptimeSeconds: number | null;
  } | null>(null);

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

  // Sync report panel state
  const [syncReportExpanded, setSyncReportExpanded] = useState(false);
  const [focusedSyncRequestId, setFocusedSyncRequestId] = useState<number | null>(null);

  // Inline action error (auto-dismissing)
  const [actionError, setActionError] = useState<string | null>(null);

  // Tab state
  const [activeTab, setActiveTab] = useState<'songs' | 'manage' | 'pre-event'>('songs');
  const helpPageId = activeTab === 'songs' ? 'event-songs' : 'event-manage'; // pre-event shares manage page

  // Pre-event collection settings
  const [collectionSettings, setCollectionSettings] = useState<CollectionSettingsResponse | null>(null);
  const { hasSeenPage, startOnboarding, onboardingActive } = useHelp();

  // Banner upload state
  const [uploadingBanner, setUploadingBanner] = useState(false);

  // Compact mode (persisted in localStorage)
  const [compactMode, setCompactMode] = useState(() => {
    try {
      return localStorage.getItem('wrzdj-compact') === 'true';
    } catch {
      return false;
    }
  });

  // Sort field + direction (persisted in localStorage per event, issue #478).
  // Migrates the legacy single `wrzdj-sort-${code}` toggle: 'priority' →
  // best_match, anything else → date_requested.
  const [sortField, setSortField] = useState<RequestSort>(() => readStoredSortField(code));
  const [sortDirection, setSortDirection] = useState<SortDirection>(() => {
    try {
      const storedDir = localStorage.getItem(`wrzdj-sortdir-${code}`);
      if (storedDir === 'asc' || storedDir === 'desc') return storedDir;
    } catch {
      // localStorage unavailable
    }
    return SORT_FIELD_DEFAULT_DIRECTION[readStoredSortField(code)];
  });

  // Changing the field snaps direction to that field's default (a separate
  // toggle then flips it). Persist both for next session.
  const handleSortFieldChange = useCallback((field: RequestSort) => {
    const direction = SORT_FIELD_DEFAULT_DIRECTION[field];
    setSortField(field);
    setSortDirection(direction);
    try {
      localStorage.setItem(`wrzdj-sortfield-${code}`, field);
      localStorage.setItem(`wrzdj-sortdir-${code}`, direction);
    } catch {
      // localStorage unavailable
    }
  }, [code]);

  const handleSortDirectionToggle = useCallback(() => {
    setSortDirection((prev) => {
      const next: SortDirection = prev === 'asc' ? 'desc' : 'asc';
      try {
        localStorage.setItem(`wrzdj-sortdir-${code}`, next);
      } catch {
        // localStorage unavailable
      }
      return next;
    });
  }, [code]);

  // Refs so polling/SSE/mutation callbacks always read the current values.
  const sortFieldRef = useRef(sortField);
  sortFieldRef.current = sortField;
  const sortDirectionRef = useRef(sortDirection);
  sortDirectionRef.current = sortDirection;
  const displayLimitRef = useRef(displayLimit);
  displayLimitRef.current = displayLimit;
  const statusFilterRef = useRef(statusFilter);
  statusFilterRef.current = statusFilter;

  // Map the tab filter to the API's `status` param: 'all' → undefined.
  const filterToStatus = (filter: StatusFilter): string | undefined =>
    filter === 'all' ? undefined : filter;

  // Single growing-window fetch: always [0, displayLimit) with the current sort
  // field/direction AND active status filter so the server returns a complete,
  // honestly-totaled page (issue #478). Reads refs so polling/SSE/mutation
  // callbacks pick up current values; callers may pass an explicit status to
  // override the active filter (e.g. right after toggling it).
  const reloadRequests = useCallback(
    async (status?: string): Promise<SongRequest[]> => {
      const resp = await api.getRequests(code, {
        status: status ?? filterToStatus(statusFilterRef.current),
        sort: sortFieldRef.current,
        direction: sortDirectionRef.current,
        limit: displayLimitRef.current,
        offset: 0,
      });
      setRequests(resp.requests);
      setRequestTotal(resp.total);
      setStatusCounts(normalizeStatusCounts(resp.status_counts));
      return resp.requests;
    },
    [code],
  );

  // Switching status tabs re-fetches server-side at offset 0 (issue #478),
  // resetting the growing window so the new filter's total is honest. We pass
  // the new status explicitly because the ref hasn't flushed this render yet.
  const handleFilterChange = useCallback(
    (filter: StatusFilter) => {
      setStatusFilter(filter);
      statusFilterRef.current = filter;
      setDisplayLimit(INITIAL_DISPLAY_LIMIT);
      displayLimitRef.current = INITIAL_DISPLAY_LIMIT;
      void reloadRequests(filterToStatus(filter)).catch(() =>
        setActionError('Failed to refresh requests'),
      );
    },
    [reloadRequests],
  );

  const toggleCompactMode = useCallback(() => {
    setCompactMode((prev) => {
      const next = !prev;
      try {
        localStorage.setItem('wrzdj-compact', String(next));
      } catch {
        // localStorage unavailable
      }
      return next;
    });
  }, []);

  // Tidal device login state
  const [showTidalLogin, setShowTidalLogin] = useState(false);
  const [tidalLoginUrl, setTidalLoginUrl] = useState('');
  const [tidalLoginCode, setTidalLoginCode] = useState('');
  const [tidalLoginPolling, setTidalLoginPolling] = useState(false);

  // Beatport login modal state
  const [showBeatportLogin, setShowBeatportLogin] = useState(false);

  // Tab title badge: show "(N) Event - WrzDJ" when backgrounded. Uses the true
  // server-side new count so it stays correct when a non-'new' filter is active
  // (the loaded `requests` window no longer contains every new row, issue #478).
  useTabTitle(event?.name ?? null, statusCounts.new);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login');
    }
  }, [isAuthenticated, isLoading, router]);

  // Auto-dismiss action errors after 5 seconds
  useEffect(() => {
    if (!actionError) return;
    const timer = setTimeout(() => setActionError(null), 5000);
    return () => clearTimeout(timer);
  }, [actionError]);

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
    }, 2000);

    // Stop polling after 10 minutes
    const timeout = setTimeout(() => {
      setTidalLoginPolling(false);
    }, 10 * 60 * 1000);

    return () => {
      clearInterval(pollInterval);
      clearTimeout(timeout);
    };
  }, [tidalLoginPolling]);

  // Fetch collection settings when pre-event tab is first opened
  useEffect(() => {
    if (activeTab === 'pre-event' && !collectionSettings && isAuthenticated) {
      api.getCollectionSettings(code).then(setCollectionSettings).catch(() => {});
    }
  }, [activeTab, collectionSettings, isAuthenticated, code]);

  // Auto-trigger onboarding for first-time visitors to this tab
  const eventLoaded = !isLoading && isAuthenticated && !loading && !!event;
  useEffect(() => {
    if (eventLoaded && !onboardingActive && !hasSeenPage(helpPageId)) {
      const timer = setTimeout(() => startOnboarding(helpPageId), 500);
      return () => clearTimeout(timer);
    }
  }, [eventLoaded, onboardingActive, helpPageId, hasSeenPage, startOnboarding]);

  const hasLoadedRef = useRef(false);

  const loadData = useCallback(async (): Promise<boolean> => {
    try {
      // Fetch the event and the collection-code-keyed data together (one round-trip).
      // getEvent stays in this batch so the request queue isn't delayed behind it.
      const [eventData, requestsData, displaySettings, tidalStatusData, beatportStatusData] = await Promise.all([
        api.getEvent(code),
        api.getRequests(code, {
          status: filterToStatus(statusFilterRef.current),
          sort: sortFieldRef.current,
          direction: sortDirectionRef.current,
          limit: displayLimitRef.current,
          offset: 0,
        }),
        api.getDisplaySettings(code).catch(() => ({ now_playing_hidden: false, now_playing_auto_hide_minutes: 10, requests_open: true, kiosk_display_only: false })),
        api.getTidalStatus().catch(() => ({ linked: false, user_id: null, expires_at: null, integration_enabled: true })),
        api.getBeatportStatus().catch(() => ({ linked: false, expires_at: null, configured: false, subscription: null, integration_enabled: true })),
      ]);
      // Commit the core queue/event + settings state immediately so the request
      // queue (and the page itself — `loading` clears in `finally`) renders as soon
      // as this data is in. It must never wait on the non-critical live-display hop.
      setEvent(eventData);
      setRequests(requestsData.requests);
      setRequestTotal(requestsData.total);
      setStatusCounts(normalizeStatusCounts(requestsData.status_counts));
      setNowPlayingHidden(displaySettings.now_playing_hidden);
      setRequestsOpen(displaySettings.requests_open ?? true);
      setKioskDisplayOnly(displaySettings.kiosk_display_only ?? false);
      const serverAutoHide = displaySettings.now_playing_auto_hide_minutes ?? 10;
      setAutoHideMinutes(serverAutoHide);
      if (!savingAutoHide) {
        setAutoHideInput(String(serverAutoHide));
      }
      setFrictionlessJoin(eventData.frictionless_join ?? false);
      setTidalStatus(tidalStatusData);
      setTidalSyncEnabled(eventData.tidal_sync_enabled ?? false);
      setBeatportStatus(beatportStatusData);
      setBeatportSyncEnabled(eventData.beatport_sync_enabled ?? false);
      setEventStatus('active');
      setError(null);
      hasLoadedRef.current = true;

      // The three live-display endpoints (now-playing / bridge-status / history)
      // resolve strictly by join_code (post-#324/#328 public-URL contract), so they
      // need event.join_code — passing the collection `code` this route is keyed on
      // would 404 in a loop. Fire them once join_code is known and commit their
      // results when they arrive; they're non-critical, so this extra hop runs in
      // the background and never blocks the queue/event render committed above.
      const liveCode = eventData.join_code;
      void Promise.all([
        api.getPlayHistory(liveCode).catch((): undefined => undefined),
        api.getNowPlaying(liveCode).catch((): undefined => undefined),
        api.getBridgeStatus(liveCode).catch(() => ({ connected: false, device_name: null, last_seen: null, circuit_breaker_state: null, buffer_size: null, plugin_id: null, deck_count: null, uptime_seconds: null })),
      ]).then(([historyData, nowPlayingData, bridgeStatusData]) => {
        if (historyData !== undefined) {
          setPlayHistory(historyData.items);
          setPlayHistoryTotal(historyData.total);
        }
        if (nowPlayingData !== undefined) {
          setNowPlaying(nowPlayingData ?? null);
        }
        setBridgeConnected(bridgeStatusData.connected);
        setBridgeDetails({
          circuitBreakerState: bridgeStatusData.circuit_breaker_state,
          bufferSize: bridgeStatusData.buffer_size,
          pluginId: bridgeStatusData.plugin_id,
          deckCount: bridgeStatusData.deck_count,
          uptimeSeconds: bridgeStatusData.uptime_seconds,
        });
      });
      return true; // Continue polling
    } catch (err) {
      if (err instanceof ApiError && err.status === 410) {
        // Event is expired/archived - try to get from archived list
        try {
          const [archivedEvents, requestsData] = await Promise.all([
            api.getArchivedEvents(),
            api.getRequests(code, {
              status: filterToStatus(statusFilterRef.current),
              sort: sortFieldRef.current,
              direction: sortDirectionRef.current,
              limit: displayLimitRef.current,
              offset: 0,
            }), // Still works for owners
          ]);
          const archivedEvent = archivedEvents.find((e) => e.code === code);
          if (archivedEvent) {
            setEvent(archivedEvent);
            setRequests(requestsData.requests);
            setRequestTotal(requestsData.total);
            setStatusCounts(normalizeStatusCounts(requestsData.status_counts));
            setEventStatus(archivedEvent.status);
            setError(null);
            return false; // Stop polling - event is expired
          }
        } catch {
          // Fall through to error handling
        }
        setError({ message: err.message, status: err.status });
        return false;
      }

      if (err instanceof ApiError) {
        if (err.status === 404) {
          setError({ message: err.message, status: err.status });
          return false; // Stop polling on 404
        }
      }
      // For transient errors: only set error if this is the initial load (no data yet)
      if (!hasLoadedRef.current) {
        setError({ message: 'Failed to load event', status: 0 });
      }
      return true; // Continue polling for transient errors
    } finally {
      setLoading(false);
    }
  }, [code]);

  // Poll every 5 seconds unless stopped (SSE handles real-time updates).
  usePollingLoop(isAuthenticated, loadData, 5_000);

  // Immediate re-fetch when the sort field/direction changes (issue #478, Bug 3)
  // — otherwise the new order only appears on the next 5s poll. Skip the first
  // render so we don't double-fetch alongside the initial load.
  const sortChangeMountRef = useRef(true);
  useEffect(() => {
    if (sortChangeMountRef.current) {
      sortChangeMountRef.current = false;
      return;
    }
    setDisplayLimit(INITIAL_DISPLAY_LIMIT);
    displayLimitRef.current = INITIAL_DISPLAY_LIMIT;
    void reloadRequests().catch(() => setActionError('Failed to refresh requests'));
  }, [sortField, sortDirection, reloadRequests]);

  // SSE: trigger immediate refresh on real-time events (new requests, bridge updates)
  const loadDataRef = useRef(loadData);
  loadDataRef.current = loadData;
  useEventStream(isAuthenticated ? code : null, {
    onRequestCreated: () => { loadDataRef.current(); },
    onNowPlayingChanged: () => { loadDataRef.current(); },
    onBridgeStatusChanged: (data) => {
      setBridgeConnected(data.connected);
      setBridgeDetails({
        circuitBreakerState: data.circuit_breaker_state ?? null,
        bufferSize: data.buffer_size ?? null,
        pluginId: data.plugin_id ?? null,
        deckCount: data.deck_count ?? null,
        uptimeSeconds: data.uptime_seconds ?? null,
      });
      loadDataRef.current();
    },
  });

  const updateStatus = async (requestId: number, status: string) => {
    setUpdating(requestId);
    try {
      const updated = await api.updateRequestStatus(requestId, status);
      setRequests((prev) =>
        prev.map((r) => (r.id === requestId ? updated : r))
      );
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to update status');
    } finally {
      setUpdating(null);
    }
  };

  const handleAcceptAll = async () => {
    setAcceptingAll(true);
    try {
      await api.acceptAllRequests(code);
      await reloadRequests();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to accept all requests');
    } finally {
      setAcceptingAll(false);
    }
  };

  const handleEditExpiry = () => {
    if (event) {
      setNewExpiryDate(toLocalDateTimeString(new Date(event.expires_at)));
      setEditingExpiry(true);
    }
  };

  const handleSaveExpiry = async () => {
    if (!newExpiryDate) return;

    setUpdatingExpiry(true);
    try {
      const expiresAt = new Date(newExpiryDate).toISOString();
      const updated = await api.updateEvent(code, { expires_at: expiresAt });
      setEvent(updated);
      setEditingExpiry(false);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to update expiry');
    } finally {
      setUpdatingExpiry(false);
    }
  };

  const handleDeleteEvent = async () => {
    setDeleting(true);
    try {
      await api.deleteEvent(code);
      router.push('/dashboard');
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to delete event');
      setDeleting(false);
      setShowDeleteConfirm(false);
    }
  };

  const handleExportCsv = async () => {
    setExporting(true);
    try {
      await api.exportEventCsv(code);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to export');
    } finally {
      setExporting(false);
    }
  };

  const handleExportPlayHistoryCsv = async () => {
    setExportingHistory(true);
    try {
      await api.exportPlayHistoryCsv(code);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to export play history');
    } finally {
      setExportingHistory(false);
    }
  };

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
    if (isNaN(value) || value < 1 || value > 1440) return;
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
    } catch {
      // Silently fail — next poll will restore the server state
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
    } catch {
      // Silently fail — next poll will restore the server state
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
    } catch {
      // Silently fail — next poll will restore the server state
    } finally {
      setTogglingFrictionless(false);
    }
  };

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
      setRequests((prev) =>
        prev.map((r) =>
          r.id === requestId
            ? { ...r }
            : r
        )
      );
      // Refresh to get updated sync_results_json from server
      await reloadRequests();
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
      await reloadRequests();
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
      await reloadRequests();
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

  const handleBannerSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const maxSize = 5 * 1024 * 1024;
    if (file.size > maxSize) {
      setActionError('File size must be under 5MB');
      e.target.value = '';
      return;
    }

    setUploadingBanner(true);
    try {
      const updated = await api.uploadEventBanner(code, file);
      setEvent(updated);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to upload banner');
    } finally {
      setUploadingBanner(false);
      e.target.value = '';
    }
  };

  const handleDeleteBanner = async () => {
    try {
      const updated = await api.deleteEventBanner(code);
      setEvent(updated);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to delete banner');
    }
  };

  // Advanced mode state
  const [deletingRequest, setDeletingRequest] = useState<number | null>(null);
  const [refreshingRequest, setRefreshingRequest] = useState<number | null>(null);
  const [rejectingAll, setRejectingAll] = useState(false);

  const handleDeleteRequest = async (requestId: number) => {
    setDeletingRequest(requestId);
    try {
      await api.deleteRequest(requestId);
      setRequests((prev) => prev.filter((r) => r.id !== requestId));
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to delete request');
    } finally {
      setDeletingRequest(null);
    }
  };

  const handleRefreshMetadata = async (requestId: number) => {
    setRefreshingRequest(requestId);
    try {
      const updated = await api.refreshRequestMetadata(requestId);
      setRequests((prev) => prev.map((r) => (r.id === requestId ? updated : r)));
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to refresh metadata');
    } finally {
      setRefreshingRequest(null);
    }
  };

  const handleEnrichAll = async () => {
    return api.enrichAllRequests(code);
  };

  const handleRejectAll = async () => {
    setRejectingAll(true);
    try {
      await api.rejectAllRequests(code);
      await reloadRequests();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to reject all requests');
    } finally {
      setRejectingAll(false);
    }
  };

  const handleBulkDelete = async (status?: string) => {
    try {
      await api.bulkDeleteRequests(code, status);
      await reloadRequests();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to bulk delete requests');
    }
  };

  const handleAcceptRecommendedTrack = async (track: RecommendedTrack) => {
    await api.submitRequest(
      code,
      track.artist,
      track.title,
      undefined,
      track.url || undefined,
      track.cover_url || undefined,
      undefined,
      {
        source: track.source,
        genre: track.genre || undefined,
        bpm: track.bpm || undefined,
        musical_key: track.key || undefined,
      },
    );
    // Refresh request list
    await reloadRequests();
  };

  const handleRefreshRequests = useCallback(async () => {
    await reloadRequests();
  }, [reloadRequests]);

  // Grow the window by a page and re-fetch. When a status filter is active the
  // caller passes it so `total` stays honest per-filter (issue #478).
  const handleLoadMore = useCallback(async (status?: string) => {
    const next = Math.min(displayLimitRef.current + 100, PUBLIC_PAGE_MAX);
    if (next === displayLimitRef.current) return;
    displayLimitRef.current = next;
    setDisplayLimit(next);
    await reloadRequests(status);
  }, [reloadRequests]);

  if (isLoading || !isAuthenticated) {
    return (
      <div className="container">
        <div className="loading">Loading...</div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="container">
        <div className="loading">Loading event...</div>
      </div>
    );
  }

  if (error || !event) {
    return (
      <div className="container">
        <EventErrorCard
          error={error}
          fallbackMessage="Event not found or expired."
          backLink={{ href: '/dashboard', label: 'Back to Dashboard' }}
        />
      </div>
    );
  }

  // Build list of connected + enabled services for sync badges
  const connectedServices: string[] = [];
  if (tidalStatus?.linked && tidalSyncEnabled) connectedServices.push('tidal');
  if (beatportStatus?.linked && beatportSyncEnabled) connectedServices.push('beatport');

  // Use API's join_url if configured, otherwise use current origin + the join_code
  // (NOT event.code — that's the collection code and would 404 the join page).
  const joinUrl = event.join_url || `${window.location.origin}/join/${event.join_code}`;
  const isExpiredOrArchived = eventStatus === 'expired' || eventStatus === 'archived';

  return (
    <div className={`container${compactMode ? ' compact' : ''}`}>
      <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', marginBottom: '0.5rem' }}>
        <button
          className="theme-toggle"
          onClick={toggleCompactMode}
          title={compactMode ? 'Switch to normal density' : 'Switch to compact density'}
          aria-label={compactMode ? 'Compact mode on' : 'Compact mode off'}
        >
          <span style={{ fontSize: '0.8rem', lineHeight: 1 }}>{compactMode ? '\u2630' : '\u2637'}</span>
          <span className="theme-toggle-label">{compactMode ? 'Dense' : 'Normal'}</span>
        </button>
        <HelpButton page={helpPageId} inline />
      </div>
      <OnboardingOverlay page={helpPageId} />

      {actionError && (
        <div style={{ background: 'var(--color-danger-subtle)', color: 'var(--color-danger)', padding: '0.75rem 1rem', borderRadius: '0.5rem', marginBottom: '1rem', fontSize: '0.875rem' }}>
          {actionError}
        </div>
      )}

      {/* 1. Header */}
      <div className="header">
        <div>
          <Link href="/dashboard" style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
            &larr; Back to Dashboard
          </Link>
          <h1 style={{ marginTop: '0.5rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '100%' }}>{event.name}</h1>
          <div style={{ marginTop: '0.5rem', fontSize: '0.875rem' }}>
            {isExpiredOrArchived ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                <span
                  className="badge"
                  style={{
                    background: eventStatus === 'archived' ? 'var(--text-tertiary)' : 'var(--color-danger)',
                    color: '#fff',
                    padding: '0.25rem 0.5rem',
                    borderRadius: '0.25rem',
                    textTransform: 'uppercase',
                    fontSize: '0.75rem',
                  }}
                >
                  {eventStatus}
                </span>
                <span style={{ color: 'var(--text-secondary)' }}>
                  {new Date(event.expires_at).toLocaleString()}
                </span>
                <button
                  className="btn btn-sm"
                  style={{ background: 'var(--color-primary)', color: 'white' }}
                  onClick={handleExportCsv}
                  disabled={exporting}
                >
                  {exporting ? 'Exporting...' : 'Export CSV'}
                </button>
                <button
                  className="btn btn-danger btn-sm"
                  onClick={() => setShowDeleteConfirm(true)}
                >
                  Delete
                </button>
              </div>
            ) : editingExpiry ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Expires:</span>
                <input
                  type="datetime-local"
                  className="input"
                  style={{ width: 'auto', padding: '0.25rem 0.5rem', fontSize: '0.875rem' }}
                  value={newExpiryDate}
                  onChange={(e) => setNewExpiryDate(e.target.value)}
                />
                <button
                  className="btn btn-primary btn-sm"
                  onClick={handleSaveExpiry}
                  disabled={updatingExpiry}
                >
                  {updatingExpiry ? 'Saving...' : 'Save'}
                </button>
                <button
                  className="btn btn-sm"
                  style={{ background: 'var(--surface-raised)' }}
                  onClick={() => setEditingExpiry(false)}
                >
                  Cancel
                </button>
              </div>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ color: 'var(--text-secondary)' }}>
                  Expires: {new Date(event.expires_at).toLocaleString()}
                </span>
                <button
                  className="btn btn-sm"
                  style={{ background: 'var(--surface-raised)' }}
                  onClick={handleEditExpiry}
                >
                  Edit
                </button>
                <button
                  className="btn btn-danger btn-sm"
                  onClick={() => setShowDeleteConfirm(true)}
                >
                  Delete
                </button>
              </div>
            )}
          </div>
        </div>
        {!isExpiredOrArchived && nowPlaying && (
          <NowPlayingBadge nowPlaying={nowPlaying} />
        )}
        <div style={{ textAlign: 'center' }}>
          <div className="code" style={{ fontSize: '2rem', color: isExpiredOrArchived ? 'var(--text-tertiary)' : 'var(--color-primary)' }}>
            {event.join_code}
          </div>
          {!isExpiredOrArchived && (
            <>
              <div className="qr-container">
                <QRCodeSVG value={joinUrl} size={100} />
              </div>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', marginTop: '0.5rem' }}>
                Scan to join
              </p>
            </>
          )}
        </div>
      </div>

      {/* Tabs or direct content for expired/archived */}
      {isExpiredOrArchived ? (
        <>
          <RequestQueueSection
            requests={requests}
            isExpiredOrArchived={isExpiredOrArchived}
            connectedServices={connectedServices}
            updating={updating}
            acceptingAll={acceptingAll}
            syncingRequest={syncingRequest}
            onUpdateStatus={updateStatus}
            onAcceptAll={handleAcceptAll}
            onSyncToTidal={handleSyncToTidal}
            onOpenTidalPicker={handleOpenTidalPicker}
            onScrollToSyncReport={handleScrollToSyncReport}
            sortField={sortField}
            sortDirection={sortDirection}
            onSortFieldChange={handleSortFieldChange}
            onSortDirectionToggle={handleSortDirectionToggle}
            total={requestTotal}
            onLoadMore={handleLoadMore}
            filter={statusFilter}
            onFilterChange={handleFilterChange}
            statusCounts={statusCounts}
          />
          <PlayHistorySection
            items={playHistory}
            total={playHistoryTotal}
            exporting={exportingHistory}
            onExport={handleExportPlayHistoryCsv}
          />
        </>
      ) : (
        <>
          <HelpSpot spotId="event-tabs" page={helpPageId} order={1} title="Tab Navigation" description="Switch between Song Management (requests, search, recommendations) and Event Management (kiosk, cloud providers, bridge).">
            <div className="event-tabs">
              <button
                className={`event-tab${activeTab === 'songs' ? ' active' : ''}`}
                onClick={() => setActiveTab('songs')}
              >
                Song Management
              </button>
              <button
                className={`event-tab${activeTab === 'manage' ? ' active' : ''}`}
                onClick={() => setActiveTab('manage')}
              >
                Event Management
              </button>
              {event && (
                <button
                  className={`event-tab${activeTab === 'pre-event' ? ' active' : ''}`}
                  onClick={() => setActiveTab('pre-event')}
                >
                  Pre-Event Voting
                  {'collection_opens_at' in event && event.collection_opens_at == null && (
                    <span style={{ marginLeft: 6, fontSize: '0.75em', opacity: 0.7 }}>
                      (off)
                    </span>
                  )}
                </button>
              )}
            </div>
          </HelpSpot>

          <div style={{ display: activeTab === 'songs' ? undefined : 'none' }}>
            <SongManagementTab
              code={code}
              requests={requests}
              isExpiredOrArchived={false}
              connectedServices={connectedServices}
              bridgeConnected={bridgeConnected}
              updating={updating}
              acceptingAll={acceptingAll}
              syncingRequest={syncingRequest}
              onUpdateStatus={updateStatus}
              onAcceptAll={handleAcceptAll}
              onSyncToTidal={handleSyncToTidal}
              onOpenTidalPicker={handleOpenTidalPicker}
              onOpenBeatportPicker={handleOpenBeatportPicker}
              onScrollToSyncReport={handleScrollToSyncReport}
              syncReportExpanded={syncReportExpanded}
              onToggleSyncReport={() => setSyncReportExpanded((prev) => !prev)}
              focusedSyncRequestId={focusedSyncRequestId}
              onClearSyncFocus={() => setFocusedSyncRequestId(null)}
              playHistory={playHistory}
              playHistoryTotal={playHistoryTotal}
              exportingHistory={exportingHistory}
              onExportPlayHistory={handleExportPlayHistoryCsv}
              tidalLinked={!!tidalStatus?.linked}
              beatportLinked={!!beatportStatus?.linked}
              onAcceptTrack={handleAcceptRecommendedTrack}
              onRefreshRequests={handleRefreshRequests}
              onRejectAll={handleRejectAll}
              onBulkDelete={handleBulkDelete}
              onDeleteRequest={handleDeleteRequest}
              onRefreshMetadata={handleRefreshMetadata}
              onEnrichAll={handleEnrichAll}
              rejectingAll={rejectingAll}
              deletingRequest={deletingRequest}
              refreshingRequest={refreshingRequest}
              sortField={sortField}
              sortDirection={sortDirection}
              onSortFieldChange={handleSortFieldChange}
              onSortDirectionToggle={handleSortDirectionToggle}
              total={requestTotal}
              onLoadMore={handleLoadMore}
              filter={statusFilter}
              onFilterChange={handleFilterChange}
              statusCounts={statusCounts}
            />
          </div>

          <div style={{ display: activeTab === 'manage' ? undefined : 'none' }}>
            <EventManagementTab
              code={code}
              event={event}
              bridgeConnected={bridgeConnected}
              bridgeDetails={bridgeDetails}
              requestsOpen={requestsOpen}
              togglingRequests={togglingRequests}
              onToggleRequests={handleToggleRequests}
              nowPlayingHidden={nowPlayingHidden}
              togglingNowPlaying={togglingNowPlaying}
              onToggleNowPlaying={handleToggleNowPlaying}
              autoHideInput={autoHideInput}
              autoHideMinutes={autoHideMinutes}
              savingAutoHide={savingAutoHide}
              onAutoHideInputChange={setAutoHideInput}
              onSaveAutoHide={handleSaveAutoHide}
              kioskDisplayOnly={kioskDisplayOnly}
              togglingDisplayOnly={togglingDisplayOnly}
              onToggleDisplayOnly={handleToggleDisplayOnly}
              frictionlessJoin={frictionlessJoin}
              togglingFrictionless={togglingFrictionless}
              onToggleFrictionless={handleToggleFrictionless}
              tidalStatus={tidalStatus}
              tidalSyncEnabled={tidalSyncEnabled}
              togglingTidalSync={togglingTidalSync}
              onToggleTidalSync={handleToggleTidalSync}
              onConnectTidal={handleConnectTidal}
              onDisconnectTidal={handleDisconnectTidal}
              beatportStatus={beatportStatus}
              beatportSyncEnabled={beatportSyncEnabled}
              togglingBeatportSync={togglingBeatportSync}
              onToggleBeatportSync={handleToggleBeatportSync}
              onConnectBeatport={handleConnectBeatport}
              onDisconnectBeatport={handleDisconnectBeatport}
              uploadingBanner={uploadingBanner}
              onBannerSelect={handleBannerSelect}
              onDeleteBanner={handleDeleteBanner}
              onPreEventEnabled={(next) => {
                setCollectionSettings(next);
                if (event) {
                  setEvent({
                    ...event,
                    collection_opens_at: next.collection_opens_at,
                    live_starts_at: next.live_starts_at,
                    submission_cap_per_guest: next.submission_cap_per_guest,
                    collection_phase_override: next.collection_phase_override,
                  } as typeof event);
                }
                setActiveTab('pre-event');
              }}
              onJumpToPreEventTab={() => setActiveTab('pre-event')}
            />
          </div>

          {collectionSettings && activeTab === 'pre-event' && (
            <PreEventVotingTab
              event={{
                code,
                name: event.name,
                collection_opens_at: collectionSettings.collection_opens_at,
                live_starts_at: collectionSettings.live_starts_at,
                submission_cap_per_guest: collectionSettings.submission_cap_per_guest,
                collection_phase_override: collectionSettings.collection_phase_override,
                phase: collectionSettings.phase,
                tidal_sync_enabled: collectionSettings.tidal_sync_enabled,
                tidal_collection_playlist_id: collectionSettings.tidal_collection_playlist_id,
                tidal_collection_bidirectional: collectionSettings.tidal_collection_bidirectional,
              }}
              tidalConnected={!!tidalStatus?.linked}
              tidalIntegrationEnabled={!!tidalStatus?.integration_enabled}
              onEventChange={(next) => setCollectionSettings((prev) => prev ? { ...prev, ...next } : prev)}
            />
          )}
        </>
      )}

      {/* Modals */}
      {showDeleteConfirm && (
        <DeleteEventModal
          eventName={event.name}
          requestCount={requests.length}
          deleting={deleting}
          onConfirm={handleDeleteEvent}
          onCancel={() => setShowDeleteConfirm(false)}
        />
      )}

      {showTidalLogin && (
        <TidalLoginModal
          loginUrl={tidalLoginUrl}
          userCode={tidalLoginCode}
          polling={tidalLoginPolling}
          onCancel={handleCancelTidalLogin}
        />
      )}

      {showBeatportLogin && (
        <BeatportLoginModal
          onSubmit={handleBeatportLogin}
          onCancel={() => setShowBeatportLogin(false)}
        />
      )}

      {showTidalPicker !== null && (
        <ServiceTrackPickerModal
          service="tidal"
          requestId={showTidalPicker}
          searchQuery={tidalSearchQuery}
          tidalResults={tidalSearchResults}
          beatportResults={[]}
          searching={searchingTidal}
          linking={linkingTrack}
          onSearchQueryChange={setTidalSearchQuery}
          onSearch={handleSearchTidal}
          onSelectTrack={handleLinkTidalTrack}
          onCancel={() => setShowTidalPicker(null)}
        />
      )}

      {showBeatportPicker !== null && (
        <ServiceTrackPickerModal
          service="beatport"
          requestId={showBeatportPicker}
          searchQuery={beatportSearchQuery}
          tidalResults={[]}
          beatportResults={beatportSearchResults}
          searching={searchingBeatport}
          linking={linkingBeatportTrack}
          onSearchQueryChange={setBeatportSearchQuery}
          onSearch={handleSearchBeatport}
          onSelectTrack={handleLinkBeatportTrack}
          onCancel={() => setShowBeatportPicker(null)}
        />
      )}
    </div>
  );
}
