// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { FONT_FAMILIES, getFontClass } from '../fonts';

describe('FONT_FAMILIES', () => {
  it('all font families include a CSS fallback', () => {
    expect(FONT_FAMILIES.body).toContain('sans-serif');
    expect(FONT_FAMILIES.display).toContain('sans-serif');
    expect(FONT_FAMILIES.mono).toContain('monospace');
  });
});

describe('getFontClass', () => {
  it('returns body class for unknown role', () => {
    expect(getFontClass('unknown' as 'body')).toBe('font-body');
  });
});
