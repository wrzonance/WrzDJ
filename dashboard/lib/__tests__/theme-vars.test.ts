import { describe, it, expect } from 'vitest';
import { getThemeVars, THEMES, type Theme } from '../theme-vars';

// Matches #rgb, #rrggbb, #rrggbbaa, and rgba(...) / rgb(...)
const CSS_COLOR_RE = /^(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\))$/;

const EXPECTED_TOKENS = [
  // Tier 1
  '--bg', '--card', '--surface-raised',
  '--text', '--text-secondary', '--text-tertiary',
  '--border', '--border-subtle', '--color-overlay',
  // Tier 2
  '--color-primary', '--color-primary-hover', '--color-primary-subtle',
  '--color-danger', '--color-danger-hover', '--color-danger-subtle',
  '--color-success', '--color-success-hover', '--color-success-subtle',
  '--color-warning', '--color-warning-hover', '--color-warning-subtle',
  '--color-admin', '--color-admin-subtle',
  // Tier 3
  '--color-link', '--color-nickname-accent', '--color-code-accent',
  '--color-focus-ring', '--color-scrollbar',
  '--color-log-info-bg', '--color-log-info-text',
  '--color-log-warning-bg', '--color-log-warning-text',
  '--color-log-error-bg', '--color-log-error-text',
  '--color-accent-checkbox', '--color-live-badge', '--color-status-accepted',
  '--color-curve-accent',
] as const;

describe('getThemeVars', () => {
  describe('returns correct variable maps for each theme', () => {
    it('returns dark theme surface values', () => {
      const vars = getThemeVars('dark');
      expect(vars['--bg']).toBe('#0a0a0a');
      expect(vars['--card']).toBe('#1a1a1a');
      expect(vars['--text']).toBe('#ededed');
      expect(vars['--text-secondary']).toBe('#9ca3af');
      expect(vars['--text-tertiary']).toBe('#6b7280');
      expect(vars['--color-primary']).toBe('#3b82f6');
      expect(vars['--color-danger']).toBe('#ef4444');
      expect(vars['--color-success']).toBe('#22c55e');
    });

    it('returns high-contrast theme with boosted contrast', () => {
      const vars = getThemeVars('high-contrast');
      expect(vars['--bg']).toBe('#000000');
      expect(vars['--text']).toBe('#ffffff');
      expect(vars['--text-secondary']).toBe('#d1d5db');
      expect(vars['--border']).toBe('#555555');
      expect(vars['--color-primary']).toBe('#60a5fa');
    });

    it('returns daylight theme as true light mode', () => {
      const vars = getThemeVars('daylight');
      expect(vars['--bg']).toBe('#f8fafc');
      expect(vars['--card']).toBe('#ffffff');
      expect(vars['--text']).toBe('#0f172a');
      expect(vars['--text-secondary']).toBe('#475569');
      expect(vars['--border']).toBe('#e2e8f0');
      expect(vars['--color-primary']).toBe('#2563eb');
    });
  });

  describe('variable keys consistency', () => {
    it('all three themes have exactly the same set of keys', () => {
      const darkKeys = Object.keys(getThemeVars('dark')).sort();
      const hcKeys = Object.keys(getThemeVars('high-contrast')).sort();
      const dayKeys = Object.keys(getThemeVars('daylight')).sort();
      expect(darkKeys).toEqual(hcKeys);
      expect(darkKeys).toEqual(dayKeys);
    });

    it('every theme includes all 38 expected tokens', () => {
      for (const theme of THEMES) {
        const vars = getThemeVars(theme);
        for (const key of EXPECTED_TOKENS) {
          expect(vars, `${theme} missing ${key}`).toHaveProperty(key);
          expect(vars[key], `${theme} ${key} is empty`).toBeTruthy();
        }
      }
    });

    it('has exactly 38 tokens — no extras, no missing', () => {
      const darkKeys = Object.keys(getThemeVars('dark'));
      expect(darkKeys).toHaveLength(38);
    });
  });

  describe('variable values are valid CSS colors', () => {
    for (const theme of ['dark', 'high-contrast', 'daylight'] as Theme[]) {
      it(`all values in ${theme} theme are valid CSS color strings`, () => {
        const vars = getThemeVars(theme);
        for (const [key, value] of Object.entries(vars)) {
          expect(value, `${theme} ${key} = "${value}" is not a valid CSS color`).toMatch(CSS_COLOR_RE);
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
