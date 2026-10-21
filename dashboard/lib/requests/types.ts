/** Status filters shared by request data helpers and the event queue UI. */
import type { RequestStatus } from '@/lib/api/types';

export type StatusFilter = 'all' | RequestStatus;
