import { describe, it, expect } from 'vitest';
import { parseCamelotKey, camelotOrdinal } from '../camelot';

describe('parseCamelotKey', () => {
  it('parses Camelot codes', () => {
    expect(parseCamelotKey('8A')).toEqual({ number: 8, letter: 'A' });
    expect(parseCamelotKey('12b')).toEqual({ number: 12, letter: 'B' });
  });
  it('parses standard key names case-insensitively', () => {
    expect(parseCamelotKey('A minor')).toEqual({ number: 8, letter: 'A' });
    expect(parseCamelotKey('C maj')).toEqual({ number: 8, letter: 'B' });
    expect(parseCamelotKey('Am')).toEqual({ number: 8, letter: 'A' });
  });
  it('parses enharmonic equivalents', () => {
    expect(parseCamelotKey('G# minor')).toEqual({ number: 1, letter: 'A' });
    expect(parseCamelotKey('Ab minor')).toEqual({ number: 1, letter: 'A' });
  });
  it('parses bare Tidal keys (default major)', () => {
    expect(parseCamelotKey('Eb')).toEqual({ number: 5, letter: 'B' });
    expect(parseCamelotKey('G')).toEqual({ number: 9, letter: 'B' });
    expect(parseCamelotKey('CSharp')).toEqual({ number: 3, letter: 'B' });
  });
  it('returns null for empty / unparseable', () => {
    expect(parseCamelotKey(null)).toBeNull();
    expect(parseCamelotKey('')).toBeNull();
    expect(parseCamelotKey('   ')).toBeNull();
    expect(parseCamelotKey('not a key')).toBeNull();
    expect(parseCamelotKey('13A')).toBeNull();
  });
});

describe('camelotOrdinal', () => {
  it('maps to number*2 + (B?1:0)', () => {
    expect(camelotOrdinal('1A')).toBe(2);
    expect(camelotOrdinal('1B')).toBe(3);
    expect(camelotOrdinal('12B')).toBe(25);
    expect(camelotOrdinal('8A')).toBe(16);
  });
  it('returns null when unparseable', () => {
    expect(camelotOrdinal(null)).toBeNull();
    expect(camelotOrdinal('xyz')).toBeNull();
  });
});
