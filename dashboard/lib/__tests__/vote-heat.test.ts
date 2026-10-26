// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { getVoteHeatStyle, getVoteHeatClass } from '../vote-heat';

describe('getVoteHeatStyle', () => {
  describe('0 votes (no styling)', () => {
    it('returns empty object for 0 votes', () => {
      const result = getVoteHeatStyle(0);
      expect(result).toEqual({});
    });
  });

  describe('1-2 votes (subtle warm tint)', () => {
    it('returns subtle warm background for 1 vote', () => {
      const result = getVoteHeatStyle(1);
      expect(result.background).toBe('rgba(251, 191, 36, 0.04)');
      expect(result.borderColor).toBeUndefined();
    });

    it('returns subtle warm background for 2 votes', () => {
      const result = getVoteHeatStyle(2);
      expect(result.background).toBe('rgba(251, 191, 36, 0.04)');
      expect(result.borderColor).toBeUndefined();
    });
  });

  describe('3-4 votes (warmer tint with subtle border)', () => {
    it('returns warmer background and subtle border for 3 votes', () => {
      const result = getVoteHeatStyle(3);
      expect(result.background).toBe('rgba(251, 191, 36, 0.08)');
      expect(result.borderColor).toBe('#f59e0b33');
    });

    it('returns warmer background and subtle border for 4 votes', () => {
      const result = getVoteHeatStyle(4);
      expect(result.background).toBe('rgba(251, 191, 36, 0.08)');
      expect(result.borderColor).toBe('#f59e0b33');
    });
  });

  describe('5-9 votes (warm glow)', () => {
    it('returns warm glow for 5 votes', () => {
      const result = getVoteHeatStyle(5);
      expect(result.background).toBe('rgba(251, 191, 36, 0.12)');
      expect(result.borderColor).toBe('#f59e0b66');
    });

    it('returns warm glow for 9 votes', () => {
      const result = getVoteHeatStyle(9);
      expect(result.background).toBe('rgba(251, 191, 36, 0.12)');
      expect(result.borderColor).toBe('#f59e0b66');
    });
  });

  describe('10+ votes (hot glow)', () => {
    it('returns hot glow for 10 votes', () => {
      const result = getVoteHeatStyle(10);
      expect(result.background).toBe('rgba(251, 191, 36, 0.18)');
      expect(result.borderColor).toBe('#f59e0b');
    });

    it('returns hot glow for 100 votes', () => {
      const result = getVoteHeatStyle(100);
      expect(result.background).toBe('rgba(251, 191, 36, 0.18)');
      expect(result.borderColor).toBe('#f59e0b');
    });
  });

  describe('boundary values', () => {
    it('boundary: 0 returns empty', () => {
      expect(getVoteHeatStyle(0)).toEqual({});
    });

    it('boundary: 1 enters low bracket', () => {
      expect(getVoteHeatStyle(1).background).toBe('rgba(251, 191, 36, 0.04)');
    });

    it('boundary: 3 enters med bracket', () => {
      expect(getVoteHeatStyle(3).background).toBe('rgba(251, 191, 36, 0.08)');
    });

    it('boundary: 5 enters high bracket', () => {
      expect(getVoteHeatStyle(5).background).toBe('rgba(251, 191, 36, 0.12)');
    });

    it('boundary: 10 enters hot bracket', () => {
      expect(getVoteHeatStyle(10).background).toBe('rgba(251, 191, 36, 0.18)');
    });
  });

  describe('edge cases', () => {
    it('negative vote count returns empty object', () => {
      expect(getVoteHeatStyle(-1)).toEqual({});
    });

    it('very large vote count stays in hot bracket', () => {
      expect(getVoteHeatStyle(10000)).toEqual({
        background: 'rgba(251, 191, 36, 0.18)',
        borderColor: '#f59e0b',
      });
    });
  });
});

describe('getVoteHeatClass', () => {
  it('returns vote-heat-0 for 0 votes', () => {
    expect(getVoteHeatClass(0)).toBe('vote-heat-0');
  });

  it('returns vote-heat-low for 1-2 votes', () => {
    expect(getVoteHeatClass(1)).toBe('vote-heat-low');
    expect(getVoteHeatClass(2)).toBe('vote-heat-low');
  });

  it('returns vote-heat-med for 3-4 votes', () => {
    expect(getVoteHeatClass(3)).toBe('vote-heat-med');
    expect(getVoteHeatClass(4)).toBe('vote-heat-med');
  });

  it('returns vote-heat-high for 5-9 votes', () => {
    expect(getVoteHeatClass(5)).toBe('vote-heat-high');
    expect(getVoteHeatClass(9)).toBe('vote-heat-high');
  });

  it('returns vote-heat-hot for 10+ votes', () => {
    expect(getVoteHeatClass(10)).toBe('vote-heat-hot');
    expect(getVoteHeatClass(100)).toBe('vote-heat-hot');
  });

  it('returns vote-heat-0 for negative count', () => {
    expect(getVoteHeatClass(-5)).toBe('vote-heat-0');
  });
});
