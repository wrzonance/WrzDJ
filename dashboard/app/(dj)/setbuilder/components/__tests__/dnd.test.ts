import { describe, it, expect } from 'vitest';
import {
  SLOT_REORDER_DND_TYPE,
  writeSlotReorderDragPayload,
  readSlotReorderDragPayload,
} from '../dnd';

function fakeDataTransfer(): DataTransfer {
  const store: Record<string, string> = {};
  return {
    effectAllowed: 'none',
    dropEffect: 'none',
    setData: (type: string, val: string) => {
      store[type] = val;
    },
    getData: (type: string) => store[type] ?? '',
  } as unknown as DataTransfer;
}

describe('slot reorder drag payload', () => {
  it('round-trips a slot id', () => {
    const dt = fakeDataTransfer();
    writeSlotReorderDragPayload(dt, 42);
    expect(dt.effectAllowed).toBe('move');
    expect(readSlotReorderDragPayload(dt)).toEqual({ slotId: 42 });
  });

  it('returns null for a missing payload', () => {
    expect(readSlotReorderDragPayload(fakeDataTransfer())).toBeNull();
  });

  it('returns null for a malformed payload', () => {
    const dt = fakeDataTransfer();
    dt.setData(SLOT_REORDER_DND_TYPE, '{"slotId":"nope"}');
    expect(readSlotReorderDragPayload(dt)).toBeNull();
  });
});
