import { describe, it, expect } from 'vitest';
import { getThemeVars, THEMES, type Theme } from '../theme-vars';
import { getPriorityScoreColor } from '../priority-score';

// Matches #rgb, #rrggbb, #rrggbbaa, and rgba(...) / rgb(...)
const CSS_COLOR_RE = /^(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\))$/;

function relativeLuminance(hex: string): number {
  const rawHex = hex.slice(1);
  const normalizedHex = rawHex.length === 3
    ? [...rawHex].map((channel) => `${channel}${channel}`).join('')
    : rawHex;
  const channels = normalizedHex.match(/.{2}/g)?.map((channel) => parseInt(channel, 16) / 255);
  if (!channels || channels.length !== 3) throw new Error(`Expected RGB hex color, got ${hex}`);
  const [red, green, blue] = channels.map((channel) =>
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function contrastRatio(foreground: string, background: string): number {
  const foregroundLuminance = relativeLuminance(foreground);
  const backgroundLuminance = relativeLuminance(background);
  const lighter = Math.max(foregroundLuminance, backgroundLuminance);
  const darker = Math.min(foregroundLuminance, backgroundLuminance);
  return (lighter + 0.05) / (darker + 0.05);
}

const EXPECTED_TOKENS = [
  // Tier 1
  '--bg', '--card', '--surface-raised',
  '--text', '--text-secondary', '--text-tertiary',
  '--text-on-bright-accent', '--text-on-status-accepted', '--text-on-primary',
  '--text-on-warning', '--text-on-priority-score', '--text-on-status-danger',
  '--text-on-status-archived',
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

    it('every theme includes all 40 expected tokens', () => {
      for (const theme of THEMES) {
        const vars = getThemeVars(theme);
        for (const key of EXPECTED_TOKENS) {
          expect(vars, `${theme} missing ${key}`).toHaveProperty(key);
          expect(vars[key], `${theme} ${key} is empty`).toBeTruthy();
        }
      }
    });

    it('has exactly 45 tokens — no extras, no missing', () => {
      const darkKeys = Object.keys(getThemeVars('dark'));
      expect(darkKeys).toHaveLength(45);
    });

    it('uses black text on bright accents in every theme', () => {
      for (const theme of THEMES) {
        expect(getThemeVars(theme)['--text-on-bright-accent']).toBe('#000');
      }
    });

    it('keeps priority-score badge text above WCAG AA for every score fill', () => {
      const vars = getThemeVars('dark');
      for (const score of [null, 0.2, 0.5, 0.8]) {
        expect(
          contrastRatio(vars['--text-on-priority-score'], getPriorityScoreColor(score)),
          `score ${score} badge contrast`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    });

    it('keeps badge text above WCAG AA contrast against success and accepted fills', () => {
      for (const theme of THEMES) {
        const vars = getThemeVars(theme);
        expect(
          contrastRatio(vars['--text-on-bright-accent'], vars['--color-success']),
          `${theme} success badge contrast`,
        ).toBeGreaterThanOrEqual(4.5);
        expect(
          contrastRatio(vars['--text-on-status-accepted'], vars['--color-status-accepted']),
          `${theme} accepted badge contrast`,
        ).toBeGreaterThanOrEqual(4.5);
        expect(
          contrastRatio(vars['--text-on-primary'], vars['--color-primary']),
          `${theme} primary badge contrast`,
        ).toBeGreaterThanOrEqual(4.5);
        expect(
          contrastRatio(vars['--text-on-warning'], vars['--color-warning']),
          `${theme} warning badge contrast`,
        ).toBeGreaterThanOrEqual(4.5);
        expect(
          contrastRatio(vars['--text-on-status-danger'], vars['--color-danger']),
          `${theme} danger status contrast`,
        ).toBeGreaterThanOrEqual(4.5);
        expect(
          contrastRatio(vars['--text-on-status-archived'], vars['--text-tertiary']),
          `${theme} archived status contrast`,
        ).toBeGreaterThanOrEqual(4.5);
      }
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
