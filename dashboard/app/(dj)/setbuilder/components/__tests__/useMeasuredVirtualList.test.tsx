import { renderHook, act } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useMeasuredVirtualList } from '../useMeasuredVirtualList';

describe('useMeasuredVirtualList', () => {
  it('returns a bounded visible range with spacer heights', () => {
    const { result } = renderHook(() =>
      useMeasuredVirtualList({
        itemCount: 500,
        estimateHeight: 48,
        viewportHeight: 240,
        scrollTop: 480,
        overscan: 2,
      }),
    );

    expect(result.current.startIdx).toBe(8);
    expect(result.current.endIdx).toBe(17);
    expect(result.current.beforeHeight).toBe(384);
    expect(result.current.afterHeight).toBe((500 - 17) * 48);
    expect(result.current.items.map((item) => item.idx)).toEqual([8, 9, 10, 11, 12, 13, 14, 15, 16]);
  });

  it('uses measured heights for offsets and scroll targets', () => {
    const { result } = renderHook(() =>
      useMeasuredVirtualList({
        itemCount: 10,
        estimateHeight: 50,
        viewportHeight: 150,
        scrollTop: 0,
        overscan: 1,
      }),
    );

    act(() => {
      result.current.setMeasuredHeight(0, 80);
      result.current.setMeasuredHeight(1, 20);
    });

    expect(result.current.scrollTopForIndex(2)).toBe(100);
    expect(result.current.indexFromScrollTop(99)).toBe(1);
    expect(result.current.indexFromScrollTop(100)).toBe(2);
  });

  it('resets measured heights when the measurement key changes', () => {
    const { result, rerender } = renderHook(
      ({ measurementKey }) =>
        useMeasuredVirtualList({
          itemCount: 10,
          estimateHeight: 50,
          viewportHeight: 150,
          scrollTop: 0,
          overscan: 1,
          measurementKey,
        }),
      { initialProps: { measurementKey: 'initial-structure' } },
    );

    act(() => {
      result.current.setMeasuredHeight(0, 80);
    });

    expect(result.current.scrollTopForIndex(1)).toBe(80);

    rerender({ measurementKey: 'reordered-structure' });

    expect(result.current.scrollTopForIndex(1)).toBe(50);
    expect(result.current.totalHeight).toBe(500);
  });

  it('clamps invalid list bounds', () => {
    const { result } = renderHook(() =>
      useMeasuredVirtualList({
        itemCount: Number.NaN,
        estimateHeight: 0,
        viewportHeight: -10,
        scrollTop: -20,
        overscan: -1,
      }),
    );

    expect(result.current.startIdx).toBe(0);
    expect(result.current.endIdx).toBe(0);
    expect(result.current.beforeHeight).toBe(0);
    expect(result.current.afterHeight).toBe(0);
    expect(result.current.totalHeight).toBe(0);
    expect(result.current.items).toEqual([]);
    expect(result.current.scrollTopForIndex(2)).toBe(0);
    expect(result.current.indexFromScrollTop(-1)).toBe(0);
  });
});
