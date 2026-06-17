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

export const SLOT_REORDER_DND_TYPE = 'application/x-wrzdj-slot-reorder';

export interface SlotReorderDragPayload {
  slotId: number;
}

export function writeSlotReorderDragPayload(dataTransfer: DataTransfer, slotId: number): void {
  dataTransfer.effectAllowed = 'move';
  dataTransfer.setData(SLOT_REORDER_DND_TYPE, JSON.stringify({ slotId }));
  dataTransfer.setData('text/plain', String(slotId));
}

export function readSlotReorderDragPayload(
  dataTransfer: DataTransfer,
): SlotReorderDragPayload | null {
  const raw = dataTransfer.getData(SLOT_REORDER_DND_TYPE);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as { slotId?: unknown };
    return typeof parsed.slotId === 'number' && Number.isInteger(parsed.slotId)
      ? { slotId: parsed.slotId }
      : null;
  } catch {
    return null;
  }
}
