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
