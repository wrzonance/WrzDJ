import type { Mock } from 'vitest';

type EventStreamHandlers = {
  onRequestCreated?: (data: { request_id: number; title: string; artist: string }) => void;
};

export interface JoinPageTestContext {
  JoinEventPage: typeof import('../page').default;
  mockApi: {
    getEvent: Mock;
    getPublicEvent: Mock;
    checkHasRequested: Mock;
    getJoinConfig: Mock;
    getMyRequests: Mock;
    getPublicRequests: Mock;
    submitRequest: Mock;
    publicVoteRequest: Mock;
    publicUnvoteRequest: Mock;
    eventSearch: Mock;
    search: Mock;
    ensureGuestName: Mock;
  };
  MockApiError: new (message: string, status?: number) => Error & { status: number };
  MockHumanVerificationRequiredError: new () => Error & { status: number };
  nicknameGateRenderSpy: Mock;
  testControls: {
    gateAutoCompletes: boolean;
    eventStreamHandlers: EventStreamHandlers | null;
  };
  setupDefaultMocks: () => void;
}
