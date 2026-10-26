// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { getBpmColor, type BpmColorResult } from '../bpm-color';

describe('getBpmColor', () => {
  describe('with average BPM available', () => {
    const avgBpm = 128;

    it('returns green for BPM within ±5 of average', () => {
      const exact = getBpmColor(128, avgBpm);
      expect(exact.tier).toBe('match');

      const close = getBpmColor(130, avgBpm);
      expect(close.tier).toBe('match');

      const lowerClose = getBpmColor(124, avgBpm);
      expect(lowerClose.tier).toBe('match');
    });

    it('returns amber for BPM 5-15 away from average', () => {
      const result = getBpmColor(140, avgBpm);
      expect(result.tier).toBe('near');

      const lower = getBpmColor(114, avgBpm);
      expect(lower.tier).toBe('near');
    });

    it('returns neutral/red for BPM >15 away from average', () => {
      const far = getBpmColor(150, avgBpm);
      expect(far.tier).toBe('far');

      const veryFar = getBpmColor(90, avgBpm);
      expect(veryFar.tier).toBe('far');
    });

    it('boundary: exactly 5 BPM away is still match', () => {
      const result = getBpmColor(133, avgBpm);
      expect(result.tier).toBe('match');
    });

    it('boundary: exactly 6 BPM away is near', () => {
      const result = getBpmColor(134, avgBpm);
      expect(result.tier).toBe('near');
    });

    it('boundary: exactly 15 BPM away is still near', () => {
      const result = getBpmColor(143, avgBpm);
      expect(result.tier).toBe('near');
    });

    it('boundary: exactly 16 BPM away is far', () => {
      const result = getBpmColor(144, avgBpm);
      expect(result.tier).toBe('far');
    });
  });

  describe('without average BPM', () => {
    it('returns neutral color when avgBpm is null', () => {
      const result = getBpmColor(128, null);
      expect(result.tier).toBe('neutral');
    });
  });

  describe('with null BPM', () => {
    it('returns neutral color when bpm is null', () => {
      const result = getBpmColor(null, 128);
      expect(result.tier).toBe('neutral');
    });

    it('returns neutral when both are null', () => {
      const result = getBpmColor(null, null);
      expect(result.tier).toBe('neutral');
    });
  });

  describe('return shape', () => {
    it('returns valid BpmColorResult with hex colors', () => {
      const result: BpmColorResult = getBpmColor(128, 128);
      expect(result.bg).toMatch(/^#[0-9a-fA-F]{6}$/);
      expect(result.text).toMatch(/^#[0-9a-fA-F]{6}$/);
      expect(result).toHaveProperty('tier');
    });

    it('all tiers return valid hex colors', () => {
      const match = getBpmColor(128, 128);
      const near = getBpmColor(140, 128);
      const far = getBpmColor(160, 128);
      const neutral = getBpmColor(null, null);

      for (const r of [match, near, far, neutral]) {
        expect(r.bg).toMatch(/^#[0-9a-fA-F]{6}$/);
        expect(r.text).toMatch(/^#[0-9a-fA-F]{6}$/);
      }
    });
  });

  describe('outlier override', () => {
    it('returns neutral when isOutlier is true, even with valid avg', () => {
      const result = getBpmColor(68, 128, true);
      expect(result.tier).toBe('neutral');
    });

    it('returns normal tier when isOutlier is false', () => {
      const result = getBpmColor(128, 128, false);
      expect(result.tier).toBe('match');
    });

    it('returns normal tier when isOutlier is undefined', () => {
      const result = getBpmColor(128, 128);
      expect(result.tier).toBe('match');
    });
  });

  describe('half-time / double-time awareness', () => {
    it('recognizes half-time BPM as close match', () => {
      // 64 BPM is half of 128 — should be treated as compatible
      const result = getBpmColor(64, 128);
      expect(result.tier).not.toBe('far');
    });

    it('recognizes double-time BPM as close match', () => {
      // 256 BPM is double of 128 — should be treated as compatible
      const result = getBpmColor(256, 128);
      expect(result.tier).not.toBe('far');
    });
  });
});
