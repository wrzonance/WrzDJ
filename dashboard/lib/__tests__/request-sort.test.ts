import { describe, it, expect } from 'vitest';
import {
  sortRequests,
  computeStatusCounts,
  filterByStatus,
  type SortableRequestRow,
} from '../request-sort';

function row(p: Partial<SortableRequestRow> & { id: number }): SortableRequestRow {
  return {
    created_at: '2026-01-01T00:00:00Z',
    accepted_at: null,
    vote_count: 0,
    bpm: null,
    musical_key: null,
    song_title: 'song',
    artist: 'artist',
    status: 'new',
    ...p,
  };
}

describe('sortRequests', () => {
  it('upvotes desc, id desc tie-break', () => {
    const rows = [
      row({ id: 1, vote_count: 5 }),
      row({ id: 2, vote_count: 5 }),
      row({ id: 3, vote_count: 9 }),
    ];
    expect(sortRequests(rows, 'upvotes', 'desc').map((r) => r.id)).toEqual([3, 2, 1]);
  });
  it('bpm asc nulls last; bpm desc nulls still last', () => {
    const rows = [row({ id: 1, bpm: 120 }), row({ id: 2, bpm: null }), row({ id: 3, bpm: 90 })];
    expect(sortRequests(rows, 'bpm', 'asc').map((r) => r.id)).toEqual([3, 1, 2]);
    expect(sortRequests(rows, 'bpm', 'desc').map((r) => r.id)).toEqual([1, 3, 2]);
  });
  it('date_accepted desc nulls last', () => {
    const rows = [
      row({ id: 1, accepted_at: '2026-02-01T00:00:00Z' }),
      row({ id: 2, accepted_at: null }),
      row({ id: 3, accepted_at: '2026-03-01T00:00:00Z' }),
    ];
    expect(sortRequests(rows, 'date_accepted', 'desc').map((r) => r.id)).toEqual([3, 1, 2]);
  });
  it('date_requested asc oldest first', () => {
    const rows = [
      row({ id: 1, created_at: '2026-03-01T00:00:00Z' }),
      row({ id: 2, created_at: '2026-01-01T00:00:00Z' }),
      row({ id: 3, created_at: '2026-02-01T00:00:00Z' }),
    ];
    expect(sortRequests(rows, 'date_requested', 'asc').map((r) => r.id)).toEqual([2, 3, 1]);
  });
  it('title asc case-insensitive', () => {
    const rows = [
      row({ id: 1, song_title: 'banana' }),
      row({ id: 2, song_title: 'Apple' }),
      row({ id: 3, song_title: 'cherry' }),
    ];
    expect(sortRequests(rows, 'title', 'asc').map((r) => r.id)).toEqual([2, 1, 3]);
  });
  it('artist desc case-insensitive', () => {
    const rows = [
      row({ id: 1, artist: 'beta' }),
      row({ id: 2, artist: 'Alpha' }),
      row({ id: 3, artist: 'gamma' }),
    ];
    expect(sortRequests(rows, 'artist', 'desc').map((r) => r.id)).toEqual([3, 1, 2]);
  });
  it('key asc by Camelot ordinal, nulls last, then title/artist/-id', () => {
    const rows = [
      row({ id: 1, musical_key: '8A' }), // ord 16
      row({ id: 2, musical_key: null }),
      row({ id: 3, musical_key: '1A' }), // ord 2
    ];
    expect(sortRequests(rows, 'key', 'asc').map((r) => r.id)).toEqual([3, 1, 2]);
    expect(sortRequests(rows, 'key', 'desc').map((r) => r.id)).toEqual([1, 3, 2]);
  });
  it('key tie-break uses title/artist ascending regardless of direction', () => {
    const rows = [
      row({ id: 1, musical_key: '8A', song_title: 'Zed' }),
      row({ id: 2, musical_key: '8A', song_title: 'Abe' }),
    ];
    // Both same ordinal; title 'Abe' < 'Zed' ascending in both directions.
    expect(sortRequests(rows, 'key', 'asc').map((r) => r.id)).toEqual([2, 1]);
    expect(sortRequests(rows, 'key', 'desc').map((r) => r.id)).toEqual([2, 1]);
  });
  it('does not mutate input', () => {
    const rows = [row({ id: 1, vote_count: 1 }), row({ id: 2, vote_count: 2 })];
    const copy = [...rows];
    sortRequests(rows, 'upvotes', 'desc');
    expect(rows).toEqual(copy);
  });
});

describe('computeStatusCounts', () => {
  it('counts per status plus all', () => {
    const rows = [
      row({ id: 1, status: 'new' }),
      row({ id: 2, status: 'new' }),
      row({ id: 3, status: 'accepted' }),
    ];
    const c = computeStatusCounts(rows);
    expect(c.all).toBe(3);
    expect(c.new).toBe(2);
    expect(c.accepted).toBe(1);
    expect(c.playing).toBe(0);
  });
  it('ignores unknown statuses in per-status counts but still totals them in all', () => {
    const rows = [row({ id: 1, status: 'weird' }), row({ id: 2, status: 'new' })];
    const c = computeStatusCounts(rows);
    expect(c.all).toBe(2);
    expect(c.new).toBe(1);
  });
});

describe('filterByStatus', () => {
  it('all returns everything; specific filters', () => {
    const rows = [row({ id: 1, status: 'new' }), row({ id: 2, status: 'accepted' })];
    expect(filterByStatus(rows, 'all').map((r) => r.id)).toEqual([1, 2]);
    expect(filterByStatus(rows, 'accepted').map((r) => r.id)).toEqual([2]);
  });
});
