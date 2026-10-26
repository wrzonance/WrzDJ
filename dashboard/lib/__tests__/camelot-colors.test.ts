// @vitest-environment node
import { describe, it, expect } from 'vitest';
import {
  getCamelotColor,
  getCamelotPosition,
  CAMELOT_COLORS,
  type CamelotColorResult,
} from '../camelot-colors';

describe('getCamelotPosition', () => {
  it('parses Camelot codes like "8A" and "12B"', () => {
    expect(getCamelotPosition('8A')).toEqual({ number: 8, letter: 'A' });
    expect(getCamelotPosition('12B')).toEqual({ number: 12, letter: 'B' });
    expect(getCamelotPosition('1A')).toEqual({ number: 1, letter: 'A' });
    expect(getCamelotPosition('1b')).toEqual({ number: 1, letter: 'B' });
  });

  it('parses full key names like "A minor" and "C major"', () => {
    expect(getCamelotPosition('A minor')).toEqual({ number: 8, letter: 'A' });
    expect(getCamelotPosition('C major')).toEqual({ number: 8, letter: 'B' });
    expect(getCamelotPosition('D minor')).toEqual({ number: 7, letter: 'A' });
    expect(getCamelotPosition('F major')).toEqual({ number: 7, letter: 'B' });
  });

  it('parses abbreviated key names like "Am", "Cm", "Cmaj"', () => {
    expect(getCamelotPosition('Am')).toEqual({ number: 8, letter: 'A' });
    expect(getCamelotPosition('Cm')).toEqual({ number: 5, letter: 'A' });
    expect(getCamelotPosition('Cmaj')).toEqual({ number: 8, letter: 'B' });
    expect(getCamelotPosition('Fmaj')).toEqual({ number: 7, letter: 'B' });
  });

  it('parses sharps and flats', () => {
    expect(getCamelotPosition('F#m')).toEqual({ number: 11, letter: 'A' });
    expect(getCamelotPosition('Bbm')).toEqual({ number: 3, letter: 'A' });
    expect(getCamelotPosition('Eb minor')).toEqual({ number: 2, letter: 'A' });
    expect(getCamelotPosition('F# major')).toEqual({ number: 2, letter: 'B' });
  });

  it('handles case insensitivity', () => {
    expect(getCamelotPosition('a minor')).toEqual({ number: 8, letter: 'A' });
    expect(getCamelotPosition('8a')).toEqual({ number: 8, letter: 'A' });
    expect(getCamelotPosition('12b')).toEqual({ number: 12, letter: 'B' });
  });

  it('returns null for invalid or empty input', () => {
    expect(getCamelotPosition(null)).toBeNull();
    expect(getCamelotPosition('')).toBeNull();
    expect(getCamelotPosition('  ')).toBeNull();
    expect(getCamelotPosition('nonsense')).toBeNull();
    expect(getCamelotPosition('13A')).toBeNull();
    expect(getCamelotPosition('0B')).toBeNull();
  });
});

describe('CAMELOT_COLORS', () => {
  it('has exactly 12 color entries', () => {
    expect(Object.keys(CAMELOT_COLORS)).toHaveLength(12);
  });

  it('all 12 positions map to distinct hues (industry-standard color wheel)', () => {
    const colors = Object.values(CAMELOT_COLORS);
    const uniqueColors = new Set(colors.map((c) => c.bg));
    expect(uniqueColors.size).toBe(12);
  });

  it('follows red-to-magenta hue progression (1=red, 7=green, 9=blue)', () => {
    // Position 1 should be reddish
    expect(CAMELOT_COLORS[1].bg).toMatch(/^#[fF][0-9a-fA-F]/);
    // Position 7 should be greenish (starts with low red channel)
    expect(CAMELOT_COLORS[7].bg).toMatch(/^#[0-4][0-9a-fA-F]/);
  });
});

describe('getCamelotColor', () => {
  it('returns colored result for valid Camelot code', () => {
    const result = getCamelotColor('8A');
    expect(result.camelotCode).toBe('8A');
    expect(result.bg).toBeTruthy();
    expect(result.text).toBeTruthy();
  });

  it('same position number returns same color for A and B variants', () => {
    const minor = getCamelotColor('8A');
    const major = getCamelotColor('8B');
    expect(minor.bg).toBe(major.bg);
    expect(minor.text).toBe(major.text);
  });

  it('parses full key names and returns correct Camelot code', () => {
    const result = getCamelotColor('A minor');
    expect(result.camelotCode).toBe('8A');
    expect(result.bg).toBeTruthy();
  });

  it('parses abbreviated key names', () => {
    expect(getCamelotColor('Am').camelotCode).toBe('8A');
    expect(getCamelotColor('Cmaj').camelotCode).toBe('8B');
  });

  it('returns neutral fallback for null/empty/unknown keys', () => {
    const nullResult = getCamelotColor(null);
    expect(nullResult.camelotCode).toBeNull();
    expect(nullResult.bg).toBeTruthy(); // should still have a fallback color

    const emptyResult = getCamelotColor('');
    expect(emptyResult.camelotCode).toBeNull();

    const unknownResult = getCamelotColor('nonsense');
    expect(unknownResult.camelotCode).toBeNull();
  });

  it('all 12 positions return valid hex color strings', () => {
    for (let i = 1; i <= 12; i++) {
      const resultA = getCamelotColor(`${i}A`);
      const resultB = getCamelotColor(`${i}B`);
      expect(resultA.bg).toMatch(/^#[0-9a-fA-F]{6}$/);
      expect(resultA.text).toMatch(/^#[0-9a-fA-F]{6}$/);
      expect(resultB.bg).toMatch(/^#[0-9a-fA-F]{6}$/);
    }
  });

  it('returns the full CamelotColorResult shape', () => {
    const result: CamelotColorResult = getCamelotColor('5A');
    expect(result).toHaveProperty('bg');
    expect(result).toHaveProperty('text');
    expect(result).toHaveProperty('camelotCode');
    expect(result.camelotCode).toBe('5A');
  });
});
