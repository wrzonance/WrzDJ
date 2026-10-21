import type { SongRequest, RequestSort, RequestStatus, SortDirection } from '@/lib/api/types';
import type { StatusFilter } from '@/lib/requests/types';
import type { computeBpmContext } from '@/lib/bpm-stats';

export interface RequestQueueToolbarProps {
  acceptingAll: boolean;
  onAcceptAll: () => void;
  onRejectAll?: () => Promise<void>;
  onBulkDelete?: (status?: string) => Promise<void>;
  onEnrichAll?: () => Promise<{ queued: number; remaining: number }>;
  rejectingAll?: boolean;
  sortField: RequestSort;
  sortDirection: SortDirection;
  onSortFieldChange: (field: RequestSort) => void;
  onSortDirectionToggle: () => void;
  total: number;
  filteredTotal?: number;
  onLoadMore?: (status?: string) => Promise<void>;
  filter: StatusFilter;
  onFilterChange: (filter: StatusFilter) => void;
  statusCounts: Record<StatusFilter, number>;
  capped?: boolean;
}

export interface RequestRowActions {
  connectedServices: string[];
  bridgeConnected?: boolean;
  updating: number | null;
  syncingRequest: number | null;
  onUpdateStatus: (requestId: number, status: RequestStatus) => void;
  onSyncToTidal: (requestId: number) => void;
  onOpenTidalPicker: (requestId: number) => void;
  onScrollToSyncReport?: (requestId: number) => void;
  onDeleteRequest?: (requestId: number) => Promise<void>;
  onRefreshMetadata?: (requestId: number) => Promise<void>;
  deletingRequest?: number | null;
  refreshingRequest?: number | null;
}

export interface RequestRowPresentation {
  isExpiredOrArchived: boolean;
  sortField: RequestSort;
  advancedMode: boolean;
  bpmContext: ReturnType<typeof computeBpmContext>;
}

export interface RequestRowProps {
  request: SongRequest;
  actions: RequestRowActions;
  presentation: RequestRowPresentation;
}
