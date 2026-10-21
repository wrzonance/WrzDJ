import type { Mock } from 'vitest';
import type { Event, RequestListResponse, SongRequest } from '@/lib/api';

export interface EventPageTestState {
  mockEventCode: string;
  mockIsAuthenticated: boolean;
  mockIsLoading: boolean;
  mockRole: string;
  capturedSongTabProps: Record<string, unknown>;
  capturedManageTabProps: Record<string, unknown>;
}

export interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
}

export interface EventPageTestContext {
  eventPageTestState: EventPageTestState;
  mockPush: Mock;
  api: typeof import('@/lib/api').api;
  ApiError: typeof import('@/lib/api').ApiError;
  EventQueuePage: typeof import('../page').default;
  mockEvent: (overrides?: Partial<Event>) => Event;
  deferred: <T>() => Deferred<T>;
  mockRequest: (overrides?: Partial<SongRequest>) => SongRequest;
  mockRequestList: (
    requests?: SongRequest[],
    overrides?: Partial<RequestListResponse>,
  ) => RequestListResponse;
  mockCollectionSettings: (
    phase?: 'pre_announce' | 'collection' | 'live' | 'closed',
  ) => Awaited<ReturnType<typeof import('@/lib/api').api.getCollectionSettings>>;
  setupDefaultMocks: () => void;
}
