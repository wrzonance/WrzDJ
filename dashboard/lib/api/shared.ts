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

// FastAPI reports request-validation failures (422) as a list of Pydantic
// items. Pydantic prefixes custom validator messages with "Value error, ";
// those are written for people and stand on their own, while its built-in
// messages ("String should have at least 2 characters") read better with the
// field name in front. Only the first item is shown: the forms are per-field.
function validationMessage(items: unknown[]): string | null {
  for (const item of items) {
    if (!item || typeof item !== 'object') continue;
    const { msg, loc } = item as { msg?: unknown; loc?: unknown };
    if (typeof msg !== 'string' || !msg) continue;
    const valueError = msg.match(/^Value error, (.+)$/);
    if (valueError) return valueError[1];
    const field = Array.isArray(loc) && loc[0] === 'body' && typeof loc[1] === 'string' ? loc[1] : null;
    return field ? `${field}: ${msg}` : msg;
  }
  return null;
}

export function apiErrorFromBody(body: unknown, status: number): ApiError {
  const errorObject = body && typeof body === 'object'
    ? body as { detail?: unknown }
    : null;
  const detail = errorObject?.detail;
  const detailObject = detail && typeof detail === 'object' && !Array.isArray(detail)
    ? detail as { code?: unknown; message?: unknown }
    : null;
  const message = typeof detail === 'string'
    ? detail
    : typeof detailObject?.message === 'string'
      ? detailObject.message
      : (Array.isArray(detail) && validationMessage(detail)) || 'Request failed';
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
