'use client';
import { useEventProviderSync } from './useEventProviderSync';
import { useEventDisplaySettings } from './useEventDisplaySettings';
import { useEventSortPreferences } from './useEventSortPreferences';
import { DEFAULT_AUTO_HIDE_MINUTES } from './eventDisplaySettings';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { useDjAccess } from '@/lib/use-dj-access';
import { api, ApiError, Event, ArchivedEvent } from '@/lib/api';
import { useEventStream } from '@/lib/use-event-stream';
import { usePollingLoop } from '@/lib/use-polling-loop';
import { useEventRequests } from '@/lib/requests/use-event-requests';
import { useAutoOnboarding } from '@/lib/help/useAutoOnboarding';
import { HelpSpot } from '@/components/help/HelpSpot';
import { PageControls } from '@/components/PageControls';
import { DensityToggle } from '@/components/DensityToggle';
import { OnboardingOverlay } from '@/components/help/OnboardingOverlay';
import { useTabTitle } from '@/lib/tab-title';
import { EventErrorCard } from '@/components/EventErrorCard';
import { DeleteEventModal } from './components/management/DeleteEventModal';
import { EventHeader } from './components/EventHeader';
import { TidalLoginModal } from './components/providers/TidalLoginModal';
import { BeatportLoginModal } from './components/providers/BeatportLoginModal';
import { ServiceTrackPickerModal } from './components/providers/ServiceTrackPickerModal';
import { RequestQueueSection } from './components/requests/RequestQueueSection';
import type { StatusFilter } from '@/lib/requests/types';
import { PlayHistorySection } from './components/requests/PlayHistorySection';
import { SongManagementTab } from './components/requests/SongManagementTab';
import { EventManagementTab } from './components/management/EventManagementTab';
import { PreEventSettingsSection } from './components/voting/PreEventSettingsSection';
import { useCollectionSettings } from './useCollectionSettings';
import { useEventQueueActions } from './useEventQueueActions';
import { useEventLifecycleActions } from './useEventLifecycleActions';
import { useEventExports } from './useEventExports';
import { useEventBannerActions } from './useEventBannerActions';
import { useEventLiveStatus } from './useEventLiveStatus';

export default function EventQueuePage() {
  const { isAuthenticated, isLoading, role, canAccess } = useDjAccess();
  const router = useRouter();
  const params = useParams();
  const code = params.code as string;

  const [event, setEvent] = useState<Event | ArchivedEvent | null>(null);
  const currentCodeRef = useRef(code);
  currentCodeRef.current = code;
  const previousCodeRef = useRef(code);
  const loadSequenceRef = useRef(0);
  const loadedCodeRef = useRef<string | null>(null);
  useEffect(() => () => {
    loadSequenceRef.current += 1;
  }, []);
  // Status filtering is client-side (issue #489): the active filter is lifted
  // here so it can feed the request hook, which filters/counts the in-memory set.
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [loading, setLoading] = useState(true);

  const [eventStatus, setEventStatus] = useState<'active' | 'expired' | 'archived'>('active');
  const [error, setError] = useState<{ message: string; status: number } | null>(null);


  const liveStatus = useEventLiveStatus({
    routeCode: code,
    joinCode: event?.code === code ? event.join_code : null,
  });
  const { playHistory, playHistoryTotal, nowPlaying, bridgeConnected, bridgeDetails } = liveStatus;

  // Inline action error (auto-dismissing)
  const [actionError, setActionError] = useState<string | null>(null);

  // Tab state
  const [activeTab, setActiveTab] = useState<'songs' | 'manage' | 'pre-event'>('songs');
  const helpPageId = activeTab === 'songs' ? 'event-songs' : 'event-manage'; // pre-event shares manage page

  const {
    settings: collectionSettings,
    loading: collectionSettingsLoading,
    error: collectionSettingsError,
    load: loadCollectionSettings,
    updateSettings: updateCollectionSettings,
    replaceSettings: replaceCollectionSettings,
  } = useCollectionSettings({
    code,
    enabled: activeTab === 'pre-event' && isAuthenticated && role !== 'pending',
  });

  // Banner upload state

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
  const { sortField, sortDirection, handleSortFieldChange, handleSortDirectionToggle } = useEventSortPreferences(code);

  // Client-side request store (issue #489): load the whole bounded event set
  // once, then sort/filter/count in memory. `visibleRequests` is the filtered +
  // client-sorted view fed to the children; `setAllRequests` backs the optimistic
  // vote/status patches; `scheduleRequestsRefetch` coalesces SSE-driven reloads.
  const {
    visibleRequests: requests,
    total: requestTotal,
    capped: requestsCapped,
    statusCounts,
    setAllRequests,
    refetch: refetchRequests,
    scheduleRefetch: scheduleRequestsRefetch,
  } = useEventRequests({
    code,
    enabled: isAuthenticated && role !== 'pending',
    sortField,
    sortDirection,
    statusFilter,
  });

  const providerSync = useEventProviderSync({ event: event as Event | null, requests, setAllRequests, refetchRequests, setActionError });
  const {
    setTidalStatus, setTidalSyncEnabled, setBeatportStatus, setBeatportSyncEnabled,
    tidalStatus, tidalSyncEnabled, togglingTidalSync, syncingRequest, showTidalPicker, setShowTidalPicker,
    tidalSearchQuery, setTidalSearchQuery, tidalSearchResults, searchingTidal, linkingTrack,
    beatportStatus, beatportSyncEnabled, togglingBeatportSync, showBeatportPicker, setShowBeatportPicker,
    beatportSearchQuery, setBeatportSearchQuery, beatportSearchResults, searchingBeatport,
    linkingBeatportTrack, syncReportExpanded, setSyncReportExpanded,
    focusedSyncRequestId, setFocusedSyncRequestId, showTidalLogin,
    tidalLoginUrl, tidalLoginCode, tidalLoginPolling, showBeatportLogin, setShowBeatportLogin,
    handleToggleTidalSync, handleConnectTidal, handleCancelTidalLogin, handleDisconnectTidal,
    handleSyncToTidal, handleOpenTidalPicker, handleSearchTidal, handleLinkTidalTrack,
    handleOpenBeatportPicker, handleSearchBeatport, handleLinkBeatportTrack,
    handleToggleBeatportSync, handleConnectBeatport, handleBeatportLogin,
    handleDisconnectBeatport, handleScrollToSyncReport,
  } = providerSync;

  const displaySettings = useEventDisplaySettings({ code, event: event as Event | null, setEvent: setEvent as React.Dispatch<React.SetStateAction<Event | null>>, setActionError });
  const {
    nowPlayingHidden, togglingNowPlaying, autoHideMinutes, autoHideInput, setAutoHideInput,
    savingAutoHide, requestsOpen, togglingRequests, kioskDisplayOnly, frictionlessJoin,
    togglingFrictionless, togglingDisplayOnly, setFrictionlessJoin, setNowPlayingHidden, setRequestsOpen, setKioskDisplayOnly,
    setAutoHideMinutes, handleToggleNowPlaying, handleSaveAutoHide, handleToggleRequests,
    handleToggleDisplayOnly, handleToggleFrictionless,
  } = displaySettings;
  const savingAutoHideRef = useRef(savingAutoHide);
  savingAutoHideRef.current = savingAutoHide;

  const queueActions = useEventQueueActions({ code, setAllRequests, refetchRequests, setActionError });
  const {
    updateStatus, handleAcceptAll, handleDeleteRequest, handleRefreshMetadata,
    handleEnrichAll, handleRejectAll, handleBulkDelete, handleAcceptRecommendedTrack,
    handleRefreshRequests, deletingRequest, refreshingRequest,
    rejectingAll, updating, acceptingAll,
  } = queueActions;
  const lifecycle = useEventLifecycleActions({ code, event, setEvent, router, setActionError });
  const {
    handleEditExpiry, handleSaveExpiry, handleDeleteEvent, editingExpiry, newExpiryDate,
    updatingExpiry, showDeleteConfirm, deleting, setEditingExpiry, setNewExpiryDate,
    setShowDeleteConfirm,
  } = lifecycle;
  const exports = useEventExports(code, setActionError);
  const {
    handleExportCsv, handleExportPlayHistoryCsv, exporting, exportingHistory,
    requestExportWarning, playHistoryExportWarning,
  } = exports;
  const bannerActions = useEventBannerActions({ code, setEvent, setActionError });
  const { handleBannerSelect, handleDeleteBanner, uploadingBanner } = bannerActions;

  // Switching status tabs now re-filters the in-memory set instantly — no fetch.
  const handleFilterChange = useCallback((filter: StatusFilter) => {
    setStatusFilter(filter);
  }, []);

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

  // Tab title badge: show "(N) Event - WrzDJ" when backgrounded. Uses the true
  // server-side new count so it stays correct when a non-'new' filter is active
  // (the loaded `requests` window no longer contains every new row, issue #478).
  useTabTitle(event?.name ?? null, statusCounts.new);

  // Auto-dismiss action errors after 5 seconds
  useEffect(() => {
    if (!actionError) return;
    const timer = setTimeout(() => setActionError(null), 5000);
    return () => clearTimeout(timer);
  }, [actionError]);

  // Auto-trigger onboarding for first-time visitors to this tab
  const eventLoaded = canAccess && !loading && !!event;
  useAutoOnboarding(helpPageId, eventLoaded);

  const loadData = useCallback(async (): Promise<boolean> => {
    const requestedCode = code;
    const requestId = ++loadSequenceRef.current;
    const isCurrentRequest = () =>
      requestId === loadSequenceRef.current && currentCodeRef.current === requestedCode;

    try {
      // Fetch the event and the collection-code-keyed settings together. The
      // request queue is owned by useEventRequests (issue #489), which loads it
      // independently, so it is no longer part of this batch or this poll.
      const [eventData, displaySettings, tidalStatusData, beatportStatusData] = await Promise.all([
        api.getEvent(code),
        api.getDisplaySettings(code).catch(() => ({ now_playing_hidden: false, now_playing_auto_hide_minutes: DEFAULT_AUTO_HIDE_MINUTES, requests_open: true, kiosk_display_only: false })),
        api.getTidalStatus().catch(() => ({ linked: false, user_id: null, expires_at: null, integration_enabled: true })),
        api.getBeatportStatus().catch(() => ({ linked: false, expires_at: null, configured: false, subscription: null, integration_enabled: true })),
      ]);
      if (!isCurrentRequest()) return true;
      // Commit the core event + settings state immediately so the page renders as
      // soon as this data is in. It must never wait on the non-critical live-display hop.
      setEvent(eventData);
      setNowPlayingHidden(displaySettings.now_playing_hidden);
      setRequestsOpen(displaySettings.requests_open ?? true);
      setKioskDisplayOnly(displaySettings.kiosk_display_only ?? false);
      const serverAutoHide = displaySettings.now_playing_auto_hide_minutes ?? DEFAULT_AUTO_HIDE_MINUTES;
      setAutoHideMinutes(serverAutoHide);
      if (!savingAutoHideRef.current) {
        setAutoHideInput(String(serverAutoHide));
      }
      setFrictionlessJoin(eventData.frictionless_join ?? false);
      setTidalStatus(tidalStatusData);
      setTidalSyncEnabled(eventData.tidal_sync_enabled ?? false);
      setBeatportStatus(beatportStatusData);
      setBeatportSyncEnabled(eventData.beatport_sync_enabled ?? false);
      setEventStatus('active');
      setError(null);
      loadedCodeRef.current = requestedCode;
      return true; // Continue polling
    } catch (err) {
      if (!isCurrentRequest()) return true;
      if (err instanceof ApiError && err.status === 410) {
        // Event is expired/archived - try to get from archived list. The request
        // queue is still loaded by useEventRequests (issue #489), which works for
        // owners regardless of archived state.
        try {
          const archivedEvents = await api.getArchivedEvents();
          if (!isCurrentRequest()) return true;
          const archivedEvent = archivedEvents.find((e) => e.code === code);
          if (archivedEvent) {
            setEvent(archivedEvent);
            setEventStatus(archivedEvent.status);
            setError(null);
            loadedCodeRef.current = requestedCode;
            return false; // Stop polling - event is expired
          }
        } catch {
          // Fall through to error handling
        }
        if (!isCurrentRequest()) return true;
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
      if (loadedCodeRef.current !== requestedCode) {
        setError({ message: 'Failed to load event', status: 0 });
      }
      return true; // Continue polling for transient errors
    } finally {
      if (isCurrentRequest()) setLoading(false);
    }
  }, [code]);

  useEffect(() => {
    if (previousCodeRef.current === code) return;
    previousCodeRef.current = code;
    loadSequenceRef.current += 1;
    loadedCodeRef.current = null;
    setEvent(null);
    setLoading(true);
    setEventStatus('active');
    setError(null);
    setActionError(null);
    setNowPlayingHidden(false);
    setRequestsOpen(true);
    setKioskDisplayOnly(false);
    setAutoHideMinutes(DEFAULT_AUTO_HIDE_MINUTES);
    setAutoHideInput(String(DEFAULT_AUTO_HIDE_MINUTES));
    setFrictionlessJoin(false);
    setTidalStatus(null);
    setTidalSyncEnabled(false);
    setBeatportStatus(null);
    setBeatportSyncEnabled(false);
    if (isAuthenticated && role !== 'pending') void loadData();
  }, [code, loadData, isAuthenticated, role]);

  // Poll every 5 seconds unless stopped (SSE handles real-time updates).
  usePollingLoop(isAuthenticated && role !== 'pending', loadData, 5_000);

  // Sort field/direction changes are now applied in-memory by useEventRequests
  // (issue #489) — instant, no re-fetch (best_match still re-fetches in the hook).

  // SSE: real-time updates. Request-affecting events drive a coalesced refetch of
  // the in-memory store (issue #489); non-queue events still refresh via loadData.
  const loadDataRef = useRef(loadData);
  loadDataRef.current = loadData;
  useEventStream(isAuthenticated && role !== 'pending' ? code : null, {
    onRequestCreated: () => { scheduleRequestsRefetch(); },
    onRequestStatusChanged: () => { scheduleRequestsRefetch(); },
    onRequestsBulkUpdate: () => { scheduleRequestsRefetch(); },
    onNowPlayingChanged: () => {
      scheduleRequestsRefetch();
      void liveStatus.refresh();
      loadDataRef.current();
    },
    onBridgeStatusChanged: (data) => {
      liveStatus.applyBridgeStatus(data, code);
      loadDataRef.current();
    },
  });

  if (isLoading || !isAuthenticated || role === 'pending') {
    return (
      <div className="container">
        <PageControls />
        <div className="loading">Loading...</div>
      </div>
    );
  }

  if (loading || (!error && event?.code !== code)) {
    return (
      <div className="container">
        <PageControls />
        <div className="loading">Loading event...</div>
      </div>
    );
  }

  if (error || !event) {
    return (
      <div className="container">
        <PageControls />
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
  const queueToolbar = {
    acceptingAll,
    onAcceptAll: handleAcceptAll,
    onRejectAll: handleRejectAll,
    onBulkDelete: handleBulkDelete,
    onEnrichAll: handleEnrichAll,
    rejectingAll,
    sortField,
    sortDirection,
    onSortFieldChange: handleSortFieldChange,
    onSortDirectionToggle: handleSortDirectionToggle,
    total: requestTotal,
    filteredTotal: statusCounts[statusFilter],
    filter: statusFilter,
    onFilterChange: handleFilterChange,
    statusCounts,
    capped: requestsCapped,
  };
  const queueRowActions = {
    connectedServices,
    bridgeConnected,
    updating,
    syncingRequest,
    onUpdateStatus: updateStatus,
    onSyncToTidal: handleSyncToTidal,
    onOpenTidalPicker: handleOpenTidalPicker,
    onScrollToSyncReport: handleScrollToSyncReport,
    onDeleteRequest: handleDeleteRequest,
    onRefreshMetadata: handleRefreshMetadata,
    deletingRequest,
    refreshingRequest,
  };

  return (
    <div className={`container${compactMode ? ' compact' : ''}`}>
      <PageControls helpPage={helpPageId}>
        <DensityToggle compact={compactMode} onToggle={toggleCompactMode} />
      </PageControls>
      <OnboardingOverlay page={helpPageId} />

      {actionError && (
        <div style={{ background: 'var(--color-danger-subtle)', color: 'var(--color-danger)', padding: '0.75rem 1rem', borderRadius: '0.5rem', marginBottom: '1rem', fontSize: '0.875rem' }}>
          {actionError}
        </div>
      )}
      {[requestExportWarning, playHistoryExportWarning].map((warning, index) => warning && (
        <div
          key={`${index}-${warning}`}
          role="status"
          aria-live="polite"
          style={{ background: 'var(--color-warning-subtle)', color: 'var(--color-warning)', padding: '0.75rem 1rem', borderRadius: '0.5rem', marginBottom: '1rem', fontSize: '0.875rem' }}
        >
          {warning}
        </div>
      ))}

      <EventHeader
        event={event}
        status={eventStatus}
        nowPlaying={nowPlaying}
        joinUrl={joinUrl}
        expiry={{
          editing: editingExpiry,
          value: newExpiryDate,
          updating: updatingExpiry,
          exporting,
          onValueChange: setNewExpiryDate,
          onEdit: handleEditExpiry,
          onSave: handleSaveExpiry,
          onCancel: () => setEditingExpiry(false),
          onExport: handleExportCsv,
          onDelete: () => setShowDeleteConfirm(true),
        }}
      />

      {/* Tabs or direct content for expired/archived */}
      {isExpiredOrArchived ? (
        <>
          <RequestQueueSection
            requests={requests}
            isExpiredOrArchived={isExpiredOrArchived}
            toolbar={queueToolbar}
            rowActions={queueRowActions}
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
            </div>
          </HelpSpot>

          <div style={{ display: activeTab === 'songs' ? undefined : 'none' }}>
            <SongManagementTab
              isExpiredOrArchived={false}
              requestQueue={{
                requests,
                toolbar: queueToolbar,
                rowActions: queueRowActions,
              }}
              syncReport={{
                requests,
                connectedServices,
                expanded: syncReportExpanded,
                onToggleExpanded: () => setSyncReportExpanded((prev) => !prev),
                focusedRequestId: focusedSyncRequestId,
                onClearFocus: () => setFocusedSyncRequestId(null),
                onRetrySync: handleSyncToTidal,
                onOpenTidalPicker: handleOpenTidalPicker,
                onOpenBeatportPicker: handleOpenBeatportPicker,
              }}
              playHistory={{ items: playHistory, total: playHistoryTotal, exporting: exportingHistory, onExport: handleExportPlayHistoryCsv }}
              recommendations={{
                code,
                tidalLinked: !!tidalStatus?.linked,
                beatportLinked: !!beatportStatus?.linked,
                onAcceptTrack: handleAcceptRecommendedTrack,
              }}
              onRefreshRequests={handleRefreshRequests}
            />
          </div>

          <div style={{ display: activeTab === 'manage' ? undefined : 'none' }}>
            <EventManagementTab
              code={code}
              event={event}
              bridge={{ connected: bridgeConnected, details: bridgeDetails }}
              kiosk={{
                requestsOpen,
                togglingRequests,
                onToggleRequests: handleToggleRequests,
                nowPlayingHidden,
                togglingNowPlaying,
                onToggleNowPlaying: handleToggleNowPlaying,
                autoHideInput,
                autoHideMinutes,
                savingAutoHide,
                onAutoHideInputChange: setAutoHideInput,
                onSaveAutoHide: handleSaveAutoHide,
                kioskDisplayOnly,
                togglingDisplayOnly,
                onToggleDisplayOnly: handleToggleDisplayOnly,
                frictionlessJoin,
                togglingFrictionless,
                onToggleFrictionless: handleToggleFrictionless,
              }}
              providers={{
                tidalStatus,
                tidalSyncEnabled,
                togglingTidalSync,
                onToggleTidalSync: handleToggleTidalSync,
                onConnectTidal: handleConnectTidal,
                onDisconnectTidal: handleDisconnectTidal,
                beatportStatus,
                beatportSyncEnabled,
                togglingBeatportSync,
                onToggleBeatportSync: handleToggleBeatportSync,
                onConnectBeatport: handleConnectBeatport,
                onDisconnectBeatport: handleDisconnectBeatport,
              }}
              customization={{
                uploadingBanner,
                onBannerSelect: handleBannerSelect,
                onDeleteBanner: handleDeleteBanner,
              }}
              preEvent={{
                onPreEventEnabled: (next) => {
                  replaceCollectionSettings(next);
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
                },
                onJumpToPreEventTab: () => setActiveTab('pre-event'),
              }}
            />
          </div>

          {activeTab === 'pre-event' && (
            <PreEventSettingsSection
              code={code}
              eventName={event.name}
              settings={collectionSettings}
              loading={collectionSettingsLoading}
              error={collectionSettingsError}
              tidalConnected={!!tidalStatus?.linked}
              tidalIntegrationEnabled={!!tidalStatus?.integration_enabled}
              onReload={() => void loadCollectionSettings()}
              onSettingsChange={updateCollectionSettings}
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
