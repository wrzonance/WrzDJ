'use client';

import { useState } from 'react';
import type { SongRequest, PlayHistoryItem, RecommendedTrack, RequestSort, SortDirection } from '@/lib/api-types';
import { RequestQueueSection } from './RequestQueueSection';
import type { StatusFilter } from './types';
import { SyncReportPanel } from './SyncReportPanel';
import { PlayHistorySection } from './PlayHistorySection';
import { RecommendationsCard } from './RecommendationsCard';
import { DjSongSearchModal } from './DjSongSearchModal';
import { HelpSpot } from '@/components/help/HelpSpot';

interface SongManagementTabProps {
  code: string;
  requests: SongRequest[];
  isExpiredOrArchived: boolean;
  connectedServices: string[];
  bridgeConnected?: boolean;
  updating: number | null;
  acceptingAll: boolean;
  syncingRequest: number | null;
  onUpdateStatus: (requestId: number, status: string) => void;
  onAcceptAll: () => void;
  onSyncToTidal: (requestId: number) => void;
  onOpenTidalPicker: (requestId: number) => void;
  onOpenBeatportPicker: (requestId: number) => void;
  onScrollToSyncReport: (requestId: number) => void;
  syncReportExpanded: boolean;
  onToggleSyncReport: () => void;
  focusedSyncRequestId: number | null;
  onClearSyncFocus: () => void;
  playHistory: PlayHistoryItem[];
  playHistoryTotal: number;
  exportingHistory: boolean;
  onExportPlayHistory: () => void;
  tidalLinked: boolean;
  beatportLinked: boolean;
  onAcceptTrack: (track: RecommendedTrack) => Promise<void>;
  onRefreshRequests: () => void;
  onRejectAll?: () => Promise<void>;
  onBulkDelete?: (status?: string) => Promise<void>;
  onDeleteRequest?: (requestId: number) => Promise<void>;
  onRefreshMetadata?: (requestId: number) => Promise<void>;
  onEnrichAll?: () => Promise<{ queued: number; remaining: number }>;
  rejectingAll?: boolean;
  deletingRequest?: number | null;
  refreshingRequest?: number | null;
  sortField: RequestSort;
  sortDirection: SortDirection;
  onSortFieldChange: (field: RequestSort) => void;
  onSortDirectionToggle: () => void;
  total: number;
  onLoadMore: (status?: string) => Promise<void>;
  filter: StatusFilter;
  onFilterChange: (filter: StatusFilter) => void;
  statusCounts: Record<StatusFilter, number>;
}

export function SongManagementTab(props: SongManagementTabProps) {
  const [showSearch, setShowSearch] = useState(false);

  return (
    <>
      {!props.isExpiredOrArchived && (
        <HelpSpot spotId="event-search-btn" page="event-songs" order={2} title="DJ Song Search" description="Search for songs to add directly to the queue.">
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '0.75rem' }}>
            <button
              className="btn btn-primary btn-sm"
              onClick={() => setShowSearch(true)}
            >
              Search For Song
            </button>
          </div>
        </HelpSpot>
      )}

      <HelpSpot spotId="event-request-queue" page="event-songs" order={3} title="Request Queue" description="Incoming song requests from guests. Filter by status, accept/reject/play.">
      <RequestQueueSection
        requests={props.requests}
        isExpiredOrArchived={props.isExpiredOrArchived}
        connectedServices={props.connectedServices}
        bridgeConnected={props.bridgeConnected}
        updating={props.updating}
        acceptingAll={props.acceptingAll}
        syncingRequest={props.syncingRequest}
        onUpdateStatus={props.onUpdateStatus}
        onAcceptAll={props.onAcceptAll}
        onSyncToTidal={props.onSyncToTidal}
        onOpenTidalPicker={props.onOpenTidalPicker}
        onScrollToSyncReport={props.onScrollToSyncReport}
        onRejectAll={props.onRejectAll}
        onBulkDelete={props.onBulkDelete}
        onDeleteRequest={props.onDeleteRequest}
        onRefreshMetadata={props.onRefreshMetadata}
        onEnrichAll={props.onEnrichAll}
        rejectingAll={props.rejectingAll}
        deletingRequest={props.deletingRequest}
        refreshingRequest={props.refreshingRequest}
        sortField={props.sortField}
        sortDirection={props.sortDirection}
        onSortFieldChange={props.onSortFieldChange}
        onSortDirectionToggle={props.onSortDirectionToggle}
        total={props.total}
        onLoadMore={props.onLoadMore}
        filter={props.filter}
        onFilterChange={props.onFilterChange}
        statusCounts={props.statusCounts}
      />
      </HelpSpot>

      <HelpSpot spotId="event-sync-report" page="event-songs" order={4} title="Sync Report" description="Shows which requests synced to playlists. Fix failures by picking the correct track.">
      <SyncReportPanel
        requests={props.requests}
        connectedServices={props.connectedServices}
        expanded={props.syncReportExpanded}
        onToggleExpanded={props.onToggleSyncReport}
        focusedRequestId={props.focusedSyncRequestId}
        onClearFocus={props.onClearSyncFocus}
        onRetrySync={props.onSyncToTidal}
        onOpenTidalPicker={props.onOpenTidalPicker}
        onOpenBeatportPicker={props.onOpenBeatportPicker}
      />
      </HelpSpot>

      <HelpSpot spotId="event-play-history" page="event-songs" order={5} title="Play History" description="Tracks detected from your DJ software via the Bridge App.">
      <PlayHistorySection
        items={props.playHistory}
        total={props.playHistoryTotal}
        exporting={props.exportingHistory}
        onExport={props.onExportPlayHistory}
      />
      </HelpSpot>

      {!props.isExpiredOrArchived && (
        <HelpSpot spotId="event-recommendations" page="event-songs" order={6} title="Recommendations" description="Get song suggestions based on requests, a playlist template, or AI.">
        <RecommendationsCard
          code={props.code}
          hasAcceptedRequests={props.requests.some(
            (r) => r.status === 'accepted' || r.status === 'played'
          )}
          tidalLinked={props.tidalLinked}
          beatportLinked={props.beatportLinked}
          onAcceptTrack={props.onAcceptTrack}
        />
        </HelpSpot>
      )}

      {showSearch && (
        <DjSongSearchModal
          code={props.code}
          onSongAdded={props.onRefreshRequests}
          onClose={() => setShowSearch(false)}
        />
      )}
    </>
  );
}
