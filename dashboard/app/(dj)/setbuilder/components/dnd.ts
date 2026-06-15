export const POOL_TRACK_DND_TYPE = 'application/x-wrzdj-pool-track';

export interface PoolTrackDragPayload {
  poolTrackId: number;
}

export function writePoolTrackDragPayload(dataTransfer: DataTransfer, poolTrackId: number): void {
  dataTransfer.effectAllowed = 'copy';
  dataTransfer.setData(POOL_TRACK_DND_TYPE, JSON.stringify({ poolTrackId }));
  dataTransfer.setData('text/plain', String(poolTrackId));
}

export function readPoolTrackDragPayload(dataTransfer: DataTransfer): PoolTrackDragPayload | null {
  const raw = dataTransfer.getData(POOL_TRACK_DND_TYPE);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as { poolTrackId?: unknown };
    return typeof parsed.poolTrackId === 'number' && Number.isInteger(parsed.poolTrackId)
      ? { poolTrackId: parsed.poolTrackId }
      : null;
  } catch {
    return null;
  }
}
