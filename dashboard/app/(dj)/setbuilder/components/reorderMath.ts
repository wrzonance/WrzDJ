import type { SlotView } from './types';

export type MoveDirection = 'up' | 'down';

/**
 * Compute the new slot-id order for moving `slotId` one position in `direction`.
 * Returns null when the move is illegal: out of bounds, unknown slot, or it would
 * displace a locked slot (locked slots are immovable anchors — same invariant as
 * the desktop drag's buildReorderedIds). Used both to perform a move and to decide
 * whether a move control is enabled, so the two can never disagree.
 */
export function buildMovedIds(
  slots: SlotView[],
  slotId: number,
  direction: MoveDirection,
): number[] | null {
  const fromIdx = slots.findIndex((s) => s.id === slotId);
  if (fromIdx < 0) return null;
  const targetIdx = direction === 'up' ? fromIdx - 1 : fromIdx + 1;
  if (targetIdx < 0 || targetIdx > slots.length - 1) return null;
  const ids = slots.map((s) => s.id);
  const without = ids.filter((id) => id !== slotId);
  without.splice(targetIdx, 0, slotId);
  // Locked slots are immovable anchors — reject any move that shifts one.
  if (slots.some((s, idx) => s.locked && without[idx] !== s.id)) return null;
  return without;
}

/**
 * Pure helper: given the current ordered slots, a slot id being dragged, and
 * an insertion index, return the new ordered id array — or null if the move is
 * a no-op, targets an unknown slot, or would displace a locked slot anchor.
 *
 * This is the desktop drag-and-drop counterpart to buildMovedIds (one-step
 * move). The two are intentionally separate parallel implementations of the
 * same locked-slot-anchor invariant — do NOT merge them.
 */
export function buildReorderedIds(
  slots: SlotView[],
  slotId: number,
  insertIdx: number,
): number[] | null {
  const fromIdx = slots.findIndex((s) => s.id === slotId);
  if (fromIdx < 0) return null;
  const target = insertIdx > fromIdx ? insertIdx - 1 : insertIdx;
  if (target === fromIdx) return null; // no-op
  const ids = slots.map((s) => s.id);
  const without = ids.filter((id) => id !== slotId);
  without.splice(target, 0, slotId);
  // Locked slots are immovable anchors — reject any move that shifts one.
  if (slots.some((s, idx) => s.locked && without[idx] !== s.id)) return null;
  return without;
}
