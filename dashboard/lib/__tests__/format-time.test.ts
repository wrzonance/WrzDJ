import { describe, it, expect } from 'vitest';
import { formatRequestTimestamp, ordinalSuffix } from '../format-time';

describe('ordinalSuffix', () => {
  it('uses st/nd/rd for 1/2/3 and th otherwise', () => {
    expect(ordinalSuffix(1)).toBe('st');
    expect(ordinalSuffix(2)).toBe('nd');
    expect(ordinalSuffix(3)).toBe('rd');
    expect(ordinalSuffix(4)).toBe('th');
    expect(ordinalSuffix(21)).toBe('st');
    expect(ordinalSuffix(22)).toBe('nd');
    expect(ordinalSuffix(23)).toBe('rd');
    expect(ordinalSuffix(31)).toBe('st');
  });

  it('treats 11/12/13 as th (teens exception)', () => {
    expect(ordinalSuffix(11)).toBe('th');
    expect(ordinalSuffix(12)).toBe('th');
    expect(ordinalSuffix(13)).toBe('th');
  });
});

describe('formatRequestTimestamp', () => {
  const now = new Date('2026-06-18T20:00:00');

  it('shows 24h time only for a same-day request', () => {
    const r = new Date('2026-06-18T14:30:05');
    expect(formatRequestTimestamp(r.toISOString(), now)).toMatch(/^\d{2}:\d{2}:\d{2}$/);
  });

  it('prefixes the ordinal month/day for an earlier day', () => {
    const r = new Date('2026-06-17T09:12:44');
    expect(formatRequestTimestamp(r.toISOString(), now)).toMatch(
      /^June 17th, \d{2}:\d{2}:\d{2}$/,
    );
  });

  it('uses st for the 1st and th for the 11th', () => {
    expect(formatRequestTimestamp(new Date('2026-05-01T10:00:00').toISOString(), now)).toMatch(
      /^May 1st, /,
    );
    expect(formatRequestTimestamp(new Date('2026-05-11T10:00:00').toISOString(), now)).toMatch(
      /^May 11th, /,
    );
  });
});
