// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { formatTabTitle } from '../tab-title';

describe('formatTabTitle', () => {
  describe('with positive newCount', () => {
    it('returns "(3) My Event - WrzDJ" for count 3', () => {
      expect(formatTabTitle('My Event', 3)).toBe('(3) My Event - WrzDJ');
    });

    it('returns "(1) Friday Night - WrzDJ" for count 1', () => {
      expect(formatTabTitle('Friday Night', 1)).toBe('(1) Friday Night - WrzDJ');
    });

    it('handles large counts', () => {
      expect(formatTabTitle('Club Session', 99)).toBe('(99) Club Session - WrzDJ');
    });
  });

  describe('with zero newCount', () => {
    it('returns "My Event - WrzDJ" for count 0', () => {
      expect(formatTabTitle('My Event', 0)).toBe('My Event - WrzDJ');
    });
  });

  describe('name truncation', () => {
    it('does not truncate names at exactly 30 characters', () => {
      const name30 = 'A'.repeat(30);
      expect(formatTabTitle(name30, 1)).toBe(`(1) ${name30} - WrzDJ`);
    });

    it('truncates names longer than 30 characters with "..."', () => {
      const longName = 'A Really Long Event Name That Exceeds Thirty Characters';
      const truncated = longName.slice(0, 30) + '...';
      expect(formatTabTitle(longName, 1)).toBe(`(1) ${truncated} - WrzDJ`);
    });

    it('truncates long name with zero count', () => {
      const longName = 'A Really Long Event Name That Exceeds Thirty Characters';
      const truncated = longName.slice(0, 30) + '...';
      expect(formatTabTitle(longName, 0)).toBe(`${truncated} - WrzDJ`);
    });
  });

  describe('edge cases', () => {
    it('handles empty string name', () => {
      expect(formatTabTitle('', 0)).toBe(' - WrzDJ');
    });

    it('handles empty string name with positive count', () => {
      expect(formatTabTitle('', 5)).toBe('(5)  - WrzDJ');
    });

    it('treats negative count as 0', () => {
      expect(formatTabTitle('My Event', -1)).toBe('My Event - WrzDJ');
    });
  });
});
