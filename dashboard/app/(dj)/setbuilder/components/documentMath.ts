import type { SetDocumentSnapshot } from '@/lib/api/types';

type DocumentPoolTrack = SetDocumentSnapshot['pool']['tracks'][number];

function slotTrackIdFromPoolTrack(track: DocumentPoolTrack): string {
  return track.track_id ?? `pool:${track.id}`;
}

/**
 * Pure helper: insert a pool track into the set document at `insertIdx`,
 * returning a new snapshot with re-numbered slot positions. Throws if the
 * pool track id is unknown.
 */
export function insertPoolTrackIntoDocument(
  snapshot: SetDocumentSnapshot,
  poolTrackId: number,
  insertIdx: number,
): SetDocumentSnapshot {
  const track = snapshot.pool.tracks.find((candidate) => candidate.id === poolTrackId);
  if (!track) throw new Error('Pool track not found');
  const sortedSlots = [...snapshot.slots].sort((a, b) => a.position - b.position || a.id - b.id);
  const boundedIdx = Math.max(0, Math.min(insertIdx, sortedSlots.length));
  const nextId = Math.max(0, ...sortedSlots.map((slot) => slot.id)) + 1;
  const nextSlots = [...sortedSlots];
  nextSlots.splice(boundedIdx, 0, {
    id: nextId,
    position: boundedIdx,
    track_id: slotTrackIdFromPoolTrack(track),
    locked: false,
    notes: null,
    transition_score: null,
    transition_warnings: null,
    target_energy: null,
  });
  return {
    ...snapshot,
    slots: nextSlots.map((slot, position) => ({ ...slot, position })),
  };
}

/** Replace a slot's track from the set's pool while preserving its other edits. */
export function replaceSlotTrackInDocument(
  snapshot: SetDocumentSnapshot,
  slotId: number,
  poolTrackId: number,
): SetDocumentSnapshot {
  const track = snapshot.pool.tracks.find((candidate) => candidate.id === poolTrackId);
  if (!track) throw new Error('Pool track not found');
  let replaced = false;
  const slots = snapshot.slots.map((slot) => {
    if (slot.id !== slotId) return slot;
    if (slot.locked) throw new Error('Cannot replace a locked slot');
    replaced = true;
    return { ...slot, track_id: slotTrackIdFromPoolTrack(track) };
  });
  if (!replaced) throw new Error('Slot not found');
  return { ...snapshot, slots };
}

/**
 * Pure helper: return a new snapshot with the given slot ids' `locked` flag
 * set to `locked`. All other slots are returned unchanged.
 */
export function lockSlotsInDocument(
  snapshot: SetDocumentSnapshot,
  slotIds: number[],
  locked: boolean,
): SetDocumentSnapshot {
  const idSet = new Set(slotIds);
  return {
    ...snapshot,
    slots: snapshot.slots.map((slot) =>
      idSet.has(slot.id) ? { ...slot, locked } : slot,
    ),
  };
}
