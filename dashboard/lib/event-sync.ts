import type { SyncResultEntry } from './api/types';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isOptionalNullableString(value: unknown): boolean {
  return value === undefined || value === null || typeof value === 'string';
}

function isOptionalNullableNumber(value: unknown): boolean {
  return (
    value === undefined ||
    value === null ||
    (typeof value === 'number' && Number.isFinite(value))
  );
}

function isOptionalNullableRecord(value: unknown): boolean {
  return value === undefined || value === null || isRecord(value);
}

function isSyncStatus(value: unknown): value is SyncResultEntry['status'] {
  return (
    value === 'matched' || value === 'added' || value === 'not_found' || value === 'error'
  );
}

function parseSyncResultEntry(value: unknown): SyncResultEntry | null {
  if (!isRecord(value)) return null;
  if (typeof value.service !== 'string' || value.service.trim() === '') return null;
  if (!isSyncStatus(value.status)) return null;
  if (
    !isOptionalNullableString(value.track_id) ||
    !isOptionalNullableString(value.track_title) ||
    !isOptionalNullableString(value.track_artist) ||
    !isOptionalNullableNumber(value.confidence) ||
    !isOptionalNullableString(value.url) ||
    !isOptionalNullableNumber(value.duration_seconds) ||
    !isOptionalNullableString(value.playlist_id) ||
    !isOptionalNullableString(value.error) ||
    !isOptionalNullableString(value.error_code) ||
    !isOptionalNullableRecord(value.extra)
  ) {
    return null;
  }

  return {
    service: value.service,
    status: value.status,
    track_id: typeof value.track_id === 'string' ? value.track_id : null,
    track_title: typeof value.track_title === 'string' ? value.track_title : null,
    track_artist: typeof value.track_artist === 'string' ? value.track_artist : null,
    confidence: typeof value.confidence === 'number' ? value.confidence : null,
    url: typeof value.url === 'string' ? value.url : null,
    duration_seconds: typeof value.duration_seconds === 'number' ? value.duration_seconds : null,
    playlist_id: typeof value.playlist_id === 'string' ? value.playlist_id : null,
    error: typeof value.error === 'string' ? value.error : null,
    error_code: typeof value.error_code === 'string' ? value.error_code : null,
    extra: isRecord(value.extra) ? value.extra : null,
  };
}

/** Parse the serialized per-request sync status returned by the event API. */
export function parseSyncResults(json: string | null): SyncResultEntry[] {
  if (!json) return [];
  try {
    const value: unknown = JSON.parse(json);
    if (!Array.isArray(value)) return [];
    return value.flatMap((entry) => {
      const parsed = parseSyncResultEntry(entry);
      return parsed ? [parsed] : [];
    });
  } catch {
    return [];
  }
}
