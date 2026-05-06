import { describe, it, expect } from 'vitest';
import { getThemeVars, THEMES, type Theme } from '../theme-vars';

const CSS_COLOR_RE = /^#[0-9a-fA-F]{3,8}$/;

describe('getThemeVars', () => {
  describe('returns correct variable maps for each theme', () => {
    it('returns dark theme variables with expected values', () => {
      const vars = getThemeVars('dark');
      expect(vars['--bg']).toBe('#0a0a0a');
      expect(vars['--card']).toBe('#1a1a1a');
      expect(vars['--text']).toBe('#ededed');
      expect(vars['--text-secondary']).toBe('#9ca3af');
      expect(vars['--text-tertiary']).toBe('#6b7280');
    });

    it('returns high-contrast theme variables with boosted contrast', () => {
      const vars = getThemeVars('high-contrast');
      expect(vars['--bg']).toBe('#000000');
      expect(vars['--card']).toBe('#1a1a1a');
      expect(vars['--text']).toBe('#ffffff');
      expect(vars['--text-secondary']).toBe('#d1d5db');
      expect(vars['--text-tertiary']).toBe('#9ca3af');
      expect(vars['--border']).toBe('#555555');
    });

    it('returns daylight theme variables with bright dark values', () => {
      const vars = getThemeVars('daylight');
      expect(vars['--bg']).toBe('#1a1a1a');
      expect(vars['--card']).toBe('#262626');
      expect(vars['--text']).toBe('#ffffff');
      expect(vars['--text-secondary']).toBe('#d1d5db');
      expect(vars['--text-tertiary']).toBe('#9ca3af');
      expect(vars['--border']).toBe('#444444');
    });
  });

  describe('variable keys consistency', () => {
    it('all three themes have the same set of keys', () => {
      const darkKeys = Object.keys(getThemeVars('dark')).sort();
      const highContrastKeys = Object.keys(getThemeVars('high-contrast')).sort();
      const daylightKeys = Object.keys(getThemeVars('daylight')).sort();

      expect(darkKeys).toEqual(highContrastKeys);
      expect(darkKeys).toEqual(daylightKeys);
    });

    it('every theme includes the core variable keys', () => {
      const coreKeys = ['--bg', '--card', '--text', '--text-secondary', '--text-tertiary', '--border'];
      for (const theme of THEMES) {
        const vars = getThemeVars(theme);
        for (const key of coreKeys) {
          expect(vars).toHaveProperty(key);
        }
      }
    });
  });

  describe('variable values are valid CSS colors', () => {
    for (const theme of ['dark', 'high-contrast', 'daylight'] as Theme[]) {
      it(`all values in ${theme} theme are valid CSS color strings`, () => {
        const vars = getThemeVars(theme);
        for (const [key, value] of Object.entries(vars)) {
          expect(value, `${theme} theme ${key}`).toMatch(CSS_COLOR_RE);
        }
      });
    }
  });

  describe('THEMES constant', () => {
    it('is a non-empty array where every entry has a getThemeVars mapping', () => {
      expect(THEMES.length).toBeGreaterThan(0);
      for (const theme of THEMES) {
        expect(() => getThemeVars(theme)).not.toThrow();
        expect(Object.keys(getThemeVars(theme)).length).toBeGreaterThan(0);
      }
    });

    it('includes the three standard themes', () => {
      expect(THEMES).toContain('dark');
      expect(THEMES).toContain('high-contrast');
      expect(THEMES).toContain('daylight');
    });
  });
});
