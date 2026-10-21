'use client';

import { useState, type ComponentProps } from 'react';
import type { RecommendedTrack } from '@/lib/api/types';
import { RequestQueueSection } from './RequestQueueSection';
import { SyncReportPanel } from '../providers/SyncReportPanel';
import { PlayHistorySection } from './PlayHistorySection';
import { RecommendationsCard } from '../recommendations/RecommendationsCard';
import { DjSongSearchModal } from './DjSongSearchModal';
import { HelpSpot } from '@/components/help/HelpSpot';

type RequestQueueProps = Omit<ComponentProps<typeof RequestQueueSection>, 'isExpiredOrArchived'>;
type SyncReportProps = ComponentProps<typeof SyncReportPanel>;
type PlayHistoryProps = ComponentProps<typeof PlayHistorySection>;

interface SongManagementTabProps {
  isExpiredOrArchived: boolean;
  requestQueue: RequestQueueProps;
  syncReport: SyncReportProps;
  playHistory: PlayHistoryProps;
  recommendations: {
    code: string;
    tidalLinked: boolean;
    beatportLinked: boolean;
    onAcceptTrack: (track: RecommendedTrack) => Promise<void>;
  };
  onRefreshRequests: () => void;
}

export function SongManagementTab({
  isExpiredOrArchived,
  requestQueue,
  syncReport,
  playHistory,
  recommendations,
  onRefreshRequests,
}: SongManagementTabProps) {
  const [showSearch, setShowSearch] = useState(false);

  return (
    <>
      {!isExpiredOrArchived && (
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
      <RequestQueueSection {...requestQueue} isExpiredOrArchived={isExpiredOrArchived} />
      </HelpSpot>

      <HelpSpot spotId="event-sync-report" page="event-songs" order={4} title="Sync Report" description="Shows which requests synced to playlists. Fix failures by picking the correct track.">
      <SyncReportPanel {...syncReport} />
      </HelpSpot>

      <HelpSpot spotId="event-play-history" page="event-songs" order={5} title="Play History" description="Tracks detected from your DJ software via the Bridge App.">
      <PlayHistorySection {...playHistory} />
      </HelpSpot>

      {!isExpiredOrArchived && (
        <HelpSpot spotId="event-recommendations" page="event-songs" order={6} title="Recommendations" description="Get song suggestions based on requests, a playlist template, or AI.">
        <RecommendationsCard
          code={recommendations.code}
          hasAcceptedRequests={requestQueue.requests.some(
            (r) => r.status === 'accepted' || r.status === 'played'
          )}
          tidalLinked={recommendations.tidalLinked}
          beatportLinked={recommendations.beatportLinked}
          onAcceptTrack={recommendations.onAcceptTrack}
        />
        </HelpSpot>
      )}

      {showSearch && (
        <DjSongSearchModal
          code={recommendations.code}
          onSongAdded={onRefreshRequests}
          onClose={() => setShowSearch(false)}
        />
      )}
    </>
  );
}
