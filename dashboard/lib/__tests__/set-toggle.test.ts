import { describe, expect, it } from 'vitest';
import { toggleSetContents, toggleSetValue } from '../set-toggle';

describe('toggleSetValue', () => {
  it('adds a missing value without mutating the current selection', () => {
    const selected = new Set(['one']);

    const updated = toggleSetValue(selected, 'two');

    expect([...selected]).toEqual(['one']);
    expect([...updated]).toEqual(['one', 'two']);
    expect(updated).not.toBe(selected);
  });

  it('removes a selected value without mutating the current selection', () => {
    const selected = new Set(['one', 'two']);

    const updated = toggleSetValue(selected, 'two');

    expect([...selected]).toEqual(['one', 'two']);
    expect([...updated]).toEqual(['one']);
    expect(updated).not.toBe(selected);
  });
});

describe('toggleSetContents', () => {
  it('clears the selection when every current value is selected', () => {
    const selected = new Set(['one', 'two']);

    const updated = toggleSetContents(selected, ['one', 'two']);

    expect([...selected]).toEqual(['one', 'two']);
    expect([...updated]).toEqual([]);
    expect(updated).not.toBe(selected);
  });

  it('selects all current values when selection is incomplete', () => {
    const selected = new Set(['one']);

    const updated = toggleSetContents(selected, ['one', 'two']);

    expect([...selected]).toEqual(['one']);
    expect([...updated]).toEqual(['one', 'two']);
    expect(updated).not.toBe(selected);
  });
});
