import { describe, expect, it } from 'vitest';
import { artGradient } from './art-gradient';

describe('artGradient', () => {
  it('returns the established palette entry for stable song seeds', () => {
    expect(artGradient('AB')).toBe('linear-gradient(135deg, #4cc9f0, #4361ee)');
    expect(artGradient('')).toBe('linear-gradient(135deg, #ff006e, #8338ec, #3a86ff)');
  });
});
