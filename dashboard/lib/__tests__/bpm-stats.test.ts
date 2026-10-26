// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { computeBpmContext, type BpmContext } from '../bpm-stats';

describe('computeBpmContext', () => {
  describe('robust average (outlier-excluded)', () => {
    it('computes simple average when no outliers', () => {
      const ctx = computeBpmContext([126, 128, 130]);
      expect(ctx.average).toBeCloseTo(128, 0);
    });

    it('excludes outliers from average', () => {
      // 15 tracks at ~128 BPM, one outlier at 68 BPM
      const bpms = [125, 126, 127, 127, 128, 128, 128, 128, 129, 129, 130, 130, 131, 132, 133, 68];
      const ctx = computeBpmContext(bpms);
      // Average should be ~128-ish, NOT dragged down by the 68
      expect(ctx.average).toBeGreaterThan(124);
      expect(ctx.average).toBeLessThan(132);
    });

    it('returns null for empty array', () => {
      const ctx = computeBpmContext([]);
      expect(ctx.average).toBeNull();
    });

    it('returns the value for single-element array', () => {
      const ctx = computeBpmContext([128]);
      expect(ctx.average).toBe(128);
    });

    it('handles two-element array', () => {
      const ctx = computeBpmContext([120, 130]);
      expect(ctx.average).toBeCloseTo(125, 0);
    });
  });

  describe('outlier detection', () => {
    it('flags a low BPM outlier in a 128 BPM cluster', () => {
      const bpms = [125, 126, 127, 128, 128, 129, 130, 131, 68];
      const ctx = computeBpmContext(bpms);
      expect(ctx.isOutlier(68)).toBe(true);
    });

    it('flags a high BPM outlier in a 128 BPM cluster', () => {
      const bpms = [125, 126, 127, 128, 128, 129, 130, 131, 200];
      const ctx = computeBpmContext(bpms);
      expect(ctx.isOutlier(200)).toBe(true);
    });

    it('does not flag values within the cluster', () => {
      const bpms = [125, 126, 127, 128, 128, 129, 130, 131];
      const ctx = computeBpmContext(bpms);
      expect(ctx.isOutlier(128)).toBe(false);
      expect(ctx.isOutlier(125)).toBe(false);
      expect(ctx.isOutlier(131)).toBe(false);
    });

    it('does not flag half-time BPM as outlier', () => {
      // 64 BPM is half of 128 — DJs recognize this as compatible
      const bpms = [125, 126, 127, 128, 128, 129, 130, 131, 64];
      const ctx = computeBpmContext(bpms);
      expect(ctx.isOutlier(64)).toBe(false);
    });

    it('does not flag double-time BPM as outlier', () => {
      // 256 BPM is double of 128
      const bpms = [125, 126, 127, 128, 128, 129, 130, 131, 256];
      const ctx = computeBpmContext(bpms);
      expect(ctx.isOutlier(256)).toBe(false);
    });

    it('returns false for any value when there are too few data points', () => {
      // With < 4 values, IQR is unreliable — no outlier flagging
      const ctx = computeBpmContext([128, 68]);
      expect(ctx.isOutlier(68)).toBe(false);
      expect(ctx.isOutlier(128)).toBe(false);
    });

    it('returns false for empty context', () => {
      const ctx = computeBpmContext([]);
      expect(ctx.isOutlier(128)).toBe(false);
    });

    it('handles uniform BPMs (IQR = 0)', () => {
      // All same BPM — nothing is an outlier
      const ctx = computeBpmContext([128, 128, 128, 128, 128]);
      expect(ctx.isOutlier(128)).toBe(false);
      // But something wildly different should be flagged
      // When IQR=0, use a fixed ±15 BPM range as fallback
      expect(ctx.isOutlier(100)).toBe(true);
    });
  });

  describe('context shape', () => {
    it('returns a BpmContext with average and isOutlier', () => {
      const ctx: BpmContext = computeBpmContext([128]);
      expect(ctx).toHaveProperty('average');
      expect(ctx).toHaveProperty('isOutlier');
      expect(typeof ctx.isOutlier).toBe('function');
    });
  });
});
