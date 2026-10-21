import { api } from '..';

function assertInvalidRequestStatusIsRejected(): void {
  // @ts-expect-error Request status values must stay within the generated status union.
  void api.updateRequestStatus(1, 'queued');
}
void assertInvalidRequestStatusIsRejected;
