import { describe, it, expect } from 'vitest';
import { getConfig } from '@testing-library/react';

// #870: a loaded CI runner can take more than Testing Library's default 1000 ms
// to render after a click, which turns any findBy/waitFor into a flake. The
// shared vitest setup raises the budget once for the whole suite; this pins it.
describe('Testing Library async timeout', () => {
  it('gives findBy/waitFor more than the 1 s default on slow runners', () => {
    expect(getConfig().asyncUtilTimeout).toBe(4000);
  });
});
