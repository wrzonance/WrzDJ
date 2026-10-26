// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { formatPriorityScore, getPriorityScoreColor } from '../priority-score';

describe('formatPriorityScore', () => {
  it('returns dash for null', () => {
    expect(formatPriorityScore(null)).toBe('--');
  });

  it('returns dash for undefined', () => {
    expect(formatPriorityScore(undefined)).toBe('--');
  });

  it('returns 0% for zero', () => {
    expect(formatPriorityScore(0)).toBe('0%');
  });

  it('returns 100% for one', () => {
    expect(formatPriorityScore(1.0)).toBe('100%');
  });

  it('rounds mid score to integer percent', () => {
    expect(formatPriorityScore(0.873)).toBe('87%');
  });

  it('formats low score correctly', () => {
    expect(formatPriorityScore(0.12)).toBe('12%');
  });
});

describe('getPriorityScoreColor', () => {
  it('returns gray for null', () => {
    expect(getPriorityScoreColor(null)).toBe('#666');
  });

  it('returns gray for undefined', () => {
    expect(getPriorityScoreColor(undefined)).toBe('#666');
  });

  it('returns green for high score', () => {
    expect(getPriorityScoreColor(0.8)).toBe('#4ade80');
  });

  it('returns green at 0.7 boundary', () => {
    expect(getPriorityScoreColor(0.7)).toBe('#4ade80');
  });

  it('returns amber for mid score', () => {
    expect(getPriorityScoreColor(0.5)).toBe('#fbbf24');
  });

  it('returns amber at 0.4 boundary', () => {
    expect(getPriorityScoreColor(0.4)).toBe('#fbbf24');
  });

  it('returns red for low score', () => {
    expect(getPriorityScoreColor(0.2)).toBe('#f87171');
  });

  it('returns red at zero', () => {
    expect(getPriorityScoreColor(0)).toBe('#f87171');
  });

  it('returns green at 1.0', () => {
    expect(getPriorityScoreColor(1.0)).toBe('#4ade80');
  });
});
