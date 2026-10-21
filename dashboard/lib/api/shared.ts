export type {
  AdminLlmAuditFilters,
  CollectEventPreview,
  CollectLeaderboardResponse,
  CollectProfileResponse,
  CollectMyPicksResponse,
  CollectPreviewResponse,
  CollectionSettingsResponse,
  CollectionSyncResponse,
  BulkReviewResponse,
  LlmStreamChunk,
} from './contracts';

export class ApiError extends Error {
  status: number;
  code?: string;
  detail?: unknown;
  constructor(message: string, status: number, code?: string, detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

export function apiErrorFromBody(body: unknown, status: number): ApiError {
  const errorObject = body && typeof body === 'object'
    ? body as { detail?: unknown }
    : null;
  const detail = errorObject?.detail;
  const detailObject = detail && typeof detail === 'object'
    ? detail as { code?: unknown; message?: unknown }
    : null;
  const message = typeof detail === 'string'
    ? detail
    : typeof detailObject?.message === 'string'
      ? detailObject.message
      : 'Request failed';
  const code = typeof detailObject?.code === 'string' ? detailObject.code : undefined;
  return new ApiError(message, status, code, detail);
}

export async function responseError(response: Response, fallback = 'Request failed'): Promise<ApiError> {
  const body = await response.json().catch(() => ({ detail: fallback }));
  return apiErrorFromBody(body, response.status);
}

export async function responseJson<T>(response: Response, fallback = 'Request failed'): Promise<T> {
  if (!response.ok) throw await responseError(response, fallback);
  return response.json();
}

export class NicknameConflictError extends Error {
  claimed: boolean;
  constructor(claimed: boolean) {
    super('nickname_taken');
    this.name = 'NicknameConflictError';
    this.claimed = claimed;
  }
}

export class HumanVerificationRequiredError extends ApiError {
  constructor() {
    super('Human verification required', 403);
    this.name = 'HumanVerificationRequiredError';
  }
}

export class EmailVerificationRequiredError extends Error {
  constructor() {
    super('email_verification_required');
    this.name = 'EmailVerificationRequiredError';
  }
}

export async function withHumanRetry<T>(
  doFetch: () => Promise<Response>,
  reverify: () => Promise<void>,
): Promise<T> {
  let res = await doFetch();
  if (res.status === 403) {
    const body = await res.clone().json().catch(() => null);
    if (body?.detail?.code === 'human_verification_required') {
      await reverify();
      res = await doFetch();
    } else if (body?.detail?.code === 'email_verification_required') {
      throw new EmailVerificationRequiredError();
    }
  }
  if (!res.ok) {
    const error = await responseError(res);
    if (error.code === 'human_verification_required') {
      throw new HumanVerificationRequiredError();
    }
    throw error;
  }
  return res.json();
}

export function getApiUrl(): string {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== 'undefined') return `http://${window.location.hostname}:8000`;
  return 'http://localhost:8000';
}

export const CSRF_HEADER_NAME = 'X-Requested-With';
export const CSRF_HEADER_VALUE = 'WrzDJ';
