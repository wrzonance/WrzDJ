import { describe, expect, it } from 'vitest';
import type { SetDocumentSnapshot } from '@/lib/api/types';
import {
  insertPoolTrackIntoDocument,
  lockSlotsInDocument,
  replaceSlotTrackInDocument,
} from '../components/documentMath';

function snapshot(): SetDocumentSnapshot {
  return {
    pool: {
      tracks: [
        { id: 7, track_id: 'provider:7' },
        { id: 8, track_id: null },
      ],
    },
    slots: [
      { id: 12, position: 2, track_id: 'slot:12', locked: false, notes: 'keep me' },
      { id: 3, position: 0, track_id: 'slot:3', locked: true, notes: null },
      { id: 9, position: 1, track_id: 'slot:9', locked: false, notes: null },
    ],
  } as SetDocumentSnapshot;
}

describe('documentMath', () => {
  it('inserts a pool track into ordered slots without mutating the snapshot', () => {
    const original = snapshot();

    const updated = insertPoolTrackIntoDocument(original, 7, 1);

    expect(updated.slots.map(({ id, position, track_id }) => ({ id, position, track_id }))).toEqual([
      { id: 3, position: 0, track_id: 'slot:3' },
      { id: 13, position: 1, track_id: 'provider:7' },
      { id: 9, position: 2, track_id: 'slot:9' },
      { id: 12, position: 3, track_id: 'slot:12' },
    ]);
    expect(original.slots.map(({ id }) => id)).toEqual([12, 3, 9]);
  });

  it('uses a pool id fallback and clamps insert positions to the end', () => {
    const updated = insertPoolTrackIntoDocument(snapshot(), 8, 99);

    expect(updated.slots.at(-1)).toMatchObject({
      id: 13,
      position: 3,
      track_id: 'pool:8',
      locked: false,
    });
  });

  it('rejects unknown pool tracks and only changes requested lock flags', () => {
    const original = snapshot();

    expect(() => insertPoolTrackIntoDocument(original, 404, 0)).toThrow('Pool track not found');
    const updated = lockSlotsInDocument(original, [9, 12], true);

    expect(updated.slots.map(({ id, locked }) => ({ id, locked }))).toEqual([
      { id: 12, locked: true },
      { id: 3, locked: true },
      { id: 9, locked: true },
    ]);
    expect(original.slots.map(({ id, locked }) => ({ id, locked }))).toEqual([
      { id: 12, locked: false },
      { id: 3, locked: true },
      { id: 9, locked: false },
    ]);
  });

  it('replaces only the selected unlocked slot track and preserves slot edits', () => {
    const original = snapshot();
    const updated = replaceSlotTrackInDocument(original, 9, 7);

    expect(updated.slots[2]).toEqual({ ...original.slots[2], track_id: 'provider:7' });
    expect(updated.slots[0]).toEqual(original.slots[0]);
    expect(original.slots[2].track_id).toBe('slot:9');
  });

  it('rejects replacement when the slot is locked or either id is missing', () => {
    const original = snapshot();

    expect(() => replaceSlotTrackInDocument(original, 404, 7)).toThrow('Slot not found');
    expect(() => replaceSlotTrackInDocument(original, 9, 404)).toThrow('Pool track not found');
    expect(() => replaceSlotTrackInDocument(original, 3, 7)).toThrow('Cannot replace a locked slot');
  });
});
