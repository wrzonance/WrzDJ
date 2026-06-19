import { describe, it, expect } from 'vitest';
import { runningJoinCode } from '../running-join-code.js';
import type { EventInfo } from '../../shared/types.js';

const eventA: EventInfo = {
  id: 1,
  code: 'AAA111',
  joinCode: 'JOINAA',
  name: 'Event A',
  isActive: true,
  expiresAt: '2026-12-31T00:00:00Z',
};
const eventB: EventInfo = {
  id: 2,
  code: 'BBB222',
  joinCode: 'JOINBB',
  name: 'Event B',
  isActive: true,
  expiresAt: '2026-12-31T00:00:00Z',
};

describe('runningJoinCode', () => {
  it('returns the selected event join code when it matches the running event', () => {
    expect(runningJoinCode(eventA, 'AAA111')).toBe('JOINAA');
  });

  it('returns null when the selection diverges from the running event', () => {
    // DJ started the bridge for A, then clicked B in the still-rendered list —
    // must NOT show B's join code for A's running bridge.
    expect(runningJoinCode(eventB, 'AAA111')).toBeNull();
  });

  it('returns null when no event is selected', () => {
    expect(runningJoinCode(null, 'AAA111')).toBeNull();
  });

  it('returns null when the bridge is not running (no running event code)', () => {
    expect(runningJoinCode(eventA, null)).toBeNull();
  });
});
