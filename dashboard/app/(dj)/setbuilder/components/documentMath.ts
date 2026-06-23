import type { SetDocumentSnapshot } from '@/lib/api-types';

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
