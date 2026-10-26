// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { getRequestEmphasisStyle, getRequestEmphasisClass } from '../request-emphasis';

describe('getRequestEmphasisStyle', () => {
  describe('new status', () => {
    it('returns blue left border and background tint', () => {
      const result = getRequestEmphasisStyle('new');
      expect(result.borderLeft).toBe('4px solid #3b82f6');
      expect(result.background).toBe('rgba(59, 130, 246, 0.05)');
    });
  });

  describe('accepted status', () => {
    it('returns purple left border and no background change', () => {
      const result = getRequestEmphasisStyle('accepted');
      expect(result.borderLeft).toBe('4px solid #8b5cf6');
      expect(result.background).toBeUndefined();
    });
  });

  describe('playing status', () => {
    it('returns green left border and no background change', () => {
      const result = getRequestEmphasisStyle('playing');
      expect(result.borderLeft).toBe('4px solid #22c55e');
      expect(result.background).toBeUndefined();
    });
  });

  describe('other statuses', () => {
    it('returns empty object for rejected status', () => {
      expect(getRequestEmphasisStyle('rejected')).toEqual({});
    });

    it('returns empty object for played status', () => {
      expect(getRequestEmphasisStyle('played')).toEqual({});
    });

    it('returns empty object for unknown status', () => {
      expect(getRequestEmphasisStyle('unknown')).toEqual({});
    });

    it('returns empty object for empty string', () => {
      expect(getRequestEmphasisStyle('')).toEqual({});
    });
  });

  describe('return shape', () => {
    it('new status has exactly borderLeft and background', () => {
      const result = getRequestEmphasisStyle('new');
      expect(Object.keys(result)).toHaveLength(2);
    });

    it('accepted status returns only borderLeft', () => {
      const result = getRequestEmphasisStyle('accepted');
      expect(Object.keys(result)).toHaveLength(1);
      expect(result).toHaveProperty('borderLeft');
    });

    it('playing status returns only borderLeft', () => {
      const result = getRequestEmphasisStyle('playing');
      expect(Object.keys(result)).toHaveLength(1);
    });
  });
});

describe('getRequestEmphasisClass', () => {
  it('returns request-new for new status', () => {
    expect(getRequestEmphasisClass('new')).toBe('request-new');
  });

  it('returns request-accepted for accepted status', () => {
    expect(getRequestEmphasisClass('accepted')).toBe('request-accepted');
  });

  it('returns request-playing for playing status', () => {
    expect(getRequestEmphasisClass('playing')).toBe('request-playing');
  });

  it('returns empty string for rejected status', () => {
    expect(getRequestEmphasisClass('rejected')).toBe('');
  });

  it('returns empty string for played status', () => {
    expect(getRequestEmphasisClass('played')).toBe('');
  });

  it('returns empty string for empty string', () => {
    expect(getRequestEmphasisClass('')).toBe('');
  });
});
