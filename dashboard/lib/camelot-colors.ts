/**
 * Camelot wheel color mapping for musical key visualization.
 *
 * Maps Camelot positions (1-12) to industry-standard hue-wheel colors,
 * matching the convention used by Mixed In Key, Rekordbox, and other DJ tools.
 * Position 1 = red, progresses through the color wheel to 12 = magenta.
 */

import { parseCamelotKey, type CamelotPosition } from './camelot';
export type { CamelotPosition } from './camelot';

export interface CamelotColorResult {
  bg: string; // hex background color
  text: string; // hex text color (contrast-safe)
  camelotCode: string | null; // e.g. "8A", null if unparseable
}

/**
 * Industry-standard Camelot wheel colors.
 * 12 positions mapped to equally-spaced hues, tuned for dark-theme visibility.
 */
export const CAMELOT_COLORS: Record<number, { bg: string; text: string }> = {
  1: { bg: '#FF3B30', text: '#FFFFFF' }, // Red
  2: { bg: '#FF6B2C', text: '#FFFFFF' }, // Orange-Red
  3: { bg: '#FF9500', text: '#FFFFFF' }, // Orange
  4: { bg: '#FFCC00', text: '#1a1a1a' }, // Gold/Amber
  5: { bg: '#E5E040', text: '#1a1a1a' }, // Yellow
  6: { bg: '#8BD44A', text: '#1a1a1a' }, // Yellow-Green
  7: { bg: '#30D158', text: '#1a1a1a' }, // Green
  8: { bg: '#32D7A0', text: '#1a1a1a' }, // Teal
  9: { bg: '#3B9EFF', text: '#FFFFFF' }, // Blue
  10: { bg: '#5856D6', text: '#FFFFFF' }, // Indigo
  11: { bg: '#AF52DE', text: '#FFFFFF' }, // Purple
  12: { bg: '#FF2D78', text: '#FFFFFF' }, // Magenta/Pink
};

const FALLBACK_COLOR: CamelotColorResult = {
  bg: '#4a4a4a',
  text: '#9ca3af',
  camelotCode: null,
};

/**
 * Parse a musical key string into a Camelot wheel position.
 * Uses the canonical parser shared with harmonic sorting, including bare Tidal keys.
 */
export function getCamelotPosition(key: string | null): CamelotPosition | null {
  return parseCamelotKey(key);
}

/**
 * Get the display color for a musical key.
 * Returns bg/text colors and the parsed Camelot code.
 * A and B variants of the same position share the same color.
 */
export function getCamelotColor(key: string | null): CamelotColorResult {
  const pos = getCamelotPosition(key);
  if (!pos) return { ...FALLBACK_COLOR };

  const color = CAMELOT_COLORS[pos.number];
  return {
    bg: color.bg,
    text: color.text,
    camelotCode: `${pos.number}${pos.letter}`,
  };
}
