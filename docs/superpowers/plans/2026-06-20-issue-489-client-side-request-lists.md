# #489 — Client-side sort/filter for both event-page request lists — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert both bounded event-page request lists (the main DJ queue and the pre-event pending-review list) from #478 server-side sort/offset to a load-once-then-sort/filter/count-in-memory model, sharing pure helpers so both lists order identically.

**Architecture:** Three shared pure units — `camelot.ts` (key → harmonic ordinal), `request-sort.ts` additions (comparators + status helpers over a minimal structural row), `load-all-pages.ts` (chunked loader to a 2000 cap) — plus a thin per-list orchestrator (`use-event-requests.ts` for the main queue). `page.tsx` swaps its server-window request slice for the hook; `PreEventVotingTab.tsx` composes the helpers and drops "Load More". Two sorts stay server-authoritative (`best_match` main, `review_order` pending) — fetched in server order, never re-sorted client-side. Live updates = coalesced (~500ms-debounced) full refetch on any SSE event; existing optimistic patches stay.

**Tech Stack:** Next.js 15 / React 19, TypeScript (strict), Vitest + jsdom + Testing Library. Vanilla CSS / inline styles only (no Tailwind, no UI framework). Dark theme.

## Global Constraints

- **FRONTEND ONLY** (`dashboard/`). No backend, no SSE-payload, no migration, no OpenAPI/type-regen changes.
- Sort parity with `server/app/services/request_sort.py` is correctness-critical and verbatim: every sort ends with `id DESC`; nullable `accepted_at`/`bpm` sort **nulls-last in both directions**; `title`/`artist` compare **case-insensitively** (`toLowerCase`); `key` sort uses the Camelot ordinal `number*2 + (B?1:0)` with the tuple `(isNull, signedOrdinal, title.toLowerCase, artist.toLowerCase, -id)`, nulls last.
- Per-field default direction (mirror, already in `request-sort.ts` `SORT_FIELD_DEFAULT_DIRECTION`): `date_requested`/`date_accepted`/`upvotes` DESC; `bpm`/`key`/`title`/`artist` ASC; `best_match` DESC.
- `best_match` (main) and `review_order` (pending) are NEVER client re-sorted — fetch in server order and render as-is.
- Safety cap = 2000 rows, loaded in 500-row chunks (`PUBLIC_PAGE_MAX = 500`, already exported from `lib/api`). If `total > 2000`: load exactly 2000 (server default order), set `capped`, show banner: `Showing 2000 of N requests — sort/filter limited to these.`
- Live updates: coalesce a burst of SSE events into ONE refetch (~500ms debounce). Keep existing optimistic local patches (vote/status `setRequests`). An `AbortController` cancels in-flight chunk loads when a newer refetch/status/sort starts.
- Do NOT touch the other ~60 `useState`s in `page.tsx` (display settings, bridge, Tidal, Beatport, etc.) — that is #506's job; editing them here would collide.
- Style: vanilla CSS / inline React styles, dark theme. Match surrounding code.
- Commit format: Conventional Commits; trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- `git checkout next-env.d.ts` before any commit if it shows dirty.
- Keep vitest coverage gates green: 68% branches / 65% functions / 78% lines / 77% statements (`dashboard/vitest.config.ts`).

---

## File Structure

| File | Responsibility |
|---|---|
| `dashboard/lib/camelot.ts` (create) | Parity port of `parse_key` + `camelotOrdinal(key) → number \| null` (`number*2 + B?1:0`). |
| `dashboard/lib/request-sort.ts` (modify) | Add `SortableRequestRow` interface, `compareRequests`/`sortRequests`, `computeStatusCounts`, `filterByStatus`. Keep existing exports. |
| `dashboard/lib/load-all-pages.ts` (create) | `loadAllPages(fetcher, opts) → {requests, total, capped}` — chunked to cap with abort support. |
| `dashboard/lib/use-event-requests.ts` (create) | Main-queue hook: load-all + coalesced SSE refetch + client sort/filter/counts + optimistic patch helpers. |
| `dashboard/app/(dj)/events/[code]/page.tsx` (modify) | Replace the request-store slice (state + reloadRequests + sort/filter/load-more + SSE request wiring) with the hook. Leave all other state untouched. |
| `dashboard/app/(dj)/events/[code]/components/RequestQueueSection.tsx` (modify) | Add optional `capped?: boolean` → cap banner; "Load More" disappears for free (loaded === total when not capped). |
| `dashboard/app/(dj)/events/[code]/components/PreEventVotingTab.tsx` (modify) | Compose shared helpers; load-all-to-cap; drop "Load More"; client sort for simple fields, server order for `review_order`; cap banner. |
| `dashboard/lib/__tests__/camelot.test.ts` (create) | ordinal mapping / enharmonics / null. |
| `dashboard/lib/__tests__/request-sort.test.ts` (modify or create) | 7 fields asc/desc parity + tie-breaks; counts; filter. |
| `dashboard/lib/__tests__/load-all-pages.test.ts` (create) | stitching, stop-at-total, cap, single-page, abort. |
| `dashboard/lib/__tests__/use-event-requests.test.ts` (create) | coalesced refetch, best_match no-resort, abort on change. |
| `dashboard/app/(dj)/events/[code]/components/__tests__/PreEventVotingTab.test.tsx` (modify) | instant client sort, review_order server order, no "Load More", cap banner. |

---

## Task 1: `camelot.ts` — key → harmonic ordinal (parity port)

**Files:**
- Create: `dashboard/lib/camelot.ts`
- Test: `dashboard/lib/__tests__/camelot.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `export interface CamelotPosition { number: number; letter: string }`
  - `export function parseCamelotKey(key: string | null | undefined): CamelotPosition | null`
  - `export function camelotOrdinal(key: string | null | undefined): number | null` — `pos.number * 2 + (pos.letter === 'B' ? 1 : 0)`, or `null` when unparseable.

**Notes for the implementer:**
- `lib/camelot-colors.ts` already has a partial parser (`getCamelotPosition`) but it lacks the Tidal bare-key / `_normalize_bare_key` handling that the backend `parse_key` has. `camelot.ts` must be the **parity-complete** port so the sort ordinal matches the server exactly. Port the full `KEY_DEFINITIONS`, the Camelot-code pattern, AND the Tidal bare-key map + bare-note ("Eb", "G", "F#" → major) handling from `server/app/services/recommendation/camelot.py`. Do not import from `camelot-colors.ts` (incomplete); this file owns parity.

- [ ] **Step 1: Write the failing tests**

```typescript
// dashboard/lib/__tests__/camelot.test.ts
import { describe, it, expect } from 'vitest';
import { parseCamelotKey, camelotOrdinal } from '../camelot';

describe('parseCamelotKey', () => {
  it('parses Camelot codes', () => {
    expect(parseCamelotKey('8A')).toEqual({ number: 8, letter: 'A' });
    expect(parseCamelotKey('12b')).toEqual({ number: 12, letter: 'B' });
  });
  it('parses standard key names case-insensitively', () => {
    expect(parseCamelotKey('A minor')).toEqual({ number: 8, letter: 'A' });
    expect(parseCamelotKey('C maj')).toEqual({ number: 8, letter: 'B' });
    expect(parseCamelotKey('Am')).toEqual({ number: 8, letter: 'A' });
  });
  it('parses enharmonic equivalents', () => {
    expect(parseCamelotKey('G# minor')).toEqual({ number: 1, letter: 'A' });
    expect(parseCamelotKey('Ab minor')).toEqual({ number: 1, letter: 'A' });
  });
  it('parses bare Tidal keys (default major)', () => {
    expect(parseCamelotKey('Eb')).toEqual({ number: 5, letter: 'B' });
    expect(parseCamelotKey('G')).toEqual({ number: 9, letter: 'B' });
    expect(parseCamelotKey('CSharp')).toEqual({ number: 3, letter: 'B' });
  });
  it('returns null for empty / unparseable', () => {
    expect(parseCamelotKey(null)).toBeNull();
    expect(parseCamelotKey('')).toBeNull();
    expect(parseCamelotKey('   ')).toBeNull();
    expect(parseCamelotKey('not a key')).toBeNull();
    expect(parseCamelotKey('13A')).toBeNull();
  });
});

describe('camelotOrdinal', () => {
  it('maps to number*2 + (B?1:0)', () => {
    expect(camelotOrdinal('1A')).toBe(2);
    expect(camelotOrdinal('1B')).toBe(3);
    expect(camelotOrdinal('12B')).toBe(25);
    expect(camelotOrdinal('8A')).toBe(16);
  });
  it('returns null when unparseable', () => {
    expect(camelotOrdinal(null)).toBeNull();
    expect(camelotOrdinal('xyz')).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd dashboard && npx vitest run lib/__tests__/camelot.test.ts`
Expected: FAIL — cannot resolve `../camelot`.

- [ ] **Step 3: Implement `camelot.ts`**

Port `server/app/services/recommendation/camelot.py` faithfully. Structure:

```typescript
/**
 * Camelot wheel key parsing for client-side harmonic sorting (issue #489).
 *
 * A parity port of server/app/services/recommendation/camelot.py `parse_key`,
 * including its Tidal bare-key handling, so the dashboard's in-memory `key` sort
 * orders rows identically to the backend. (lib/camelot-colors.ts has a partial
 * parser for the color badge but omits the Tidal bare-key path — this file owns
 * the parity-complete parser the sort needs.)
 */

export interface CamelotPosition {
  number: number; // 1-12
  letter: string; // "A" (minor) or "B" (major)
}

// [num, letter, names[]] — verbatim from camelot.py _KEY_DEFINITIONS (lowercased names).
const KEY_DEFINITIONS: [number, string, string[]][] = [
  [1, 'A', ['a-flat minor', 'ab minor', 'ab min', 'abm', 'g# minor', 'g#m', 'g# min']],
  [2, 'A', ['e-flat minor', 'eb minor', 'eb min', 'ebm', 'd# minor', 'd#m', 'd# min']],
  [3, 'A', ['b-flat minor', 'bb minor', 'bb min', 'bbm', 'a# minor', 'a#m', 'a# min']],
  [4, 'A', ['f minor', 'f min', 'fm']],
  [5, 'A', ['c minor', 'c min', 'cm']],
  [6, 'A', ['g minor', 'g min', 'gm']],
  [7, 'A', ['d minor', 'd min', 'dm']],
  [8, 'A', ['a minor', 'a min', 'am']],
  [9, 'A', ['e minor', 'e min', 'em']],
  [10, 'A', ['b minor', 'b min', 'bm']],
  [11, 'A', ['f-sharp minor', 'f# minor', 'f# min', 'f#m', 'gb minor', 'gbm', 'gb min']],
  [12, 'A', ['d-flat minor', 'db minor', 'db min', 'dbm', 'c# minor', 'c#m', 'c# min']],
  [1, 'B', ['b major', 'b maj', 'bmaj']],
  [2, 'B', ['f-sharp major', 'f# major', 'f# maj', 'f#maj', 'gb major', 'gbmaj', 'gb maj']],
  [3, 'B', ['d-flat major', 'db major', 'db maj', 'dbmaj', 'c# major', 'c#maj', 'c# maj']],
  [4, 'B', ['a-flat major', 'ab major', 'ab maj', 'abmaj', 'g# major', 'g#maj', 'g# maj']],
  [5, 'B', ['e-flat major', 'eb major', 'eb maj', 'ebmaj', 'd# major', 'd#maj', 'd# maj']],
  [6, 'B', ['b-flat major', 'bb major', 'bb maj', 'bbmaj', 'a# major', 'a#maj', 'a# maj']],
  [7, 'B', ['f major', 'f maj', 'fmaj']],
  [8, 'B', ['c major', 'c maj', 'cmaj']],
  [9, 'B', ['g major', 'g maj', 'gmaj']],
  [10, 'B', ['d major', 'd maj', 'dmaj']],
  [11, 'B', ['a major', 'a maj', 'amaj']],
  [12, 'B', ['e major', 'e maj', 'emaj']],
];

const CAMELOT_MAP = new Map<string, CamelotPosition>();
for (const [num, letter, names] of KEY_DEFINITIONS) {
  const pos: CamelotPosition = { number: num, letter };
  CAMELOT_MAP.set(`${num}${letter}`, pos);
  CAMELOT_MAP.set(`${num}${letter.toLowerCase()}`, pos);
  for (const name of names) CAMELOT_MAP.set(name, pos);
}

// Tidal "CSharp"/"FSharp" → standard notation (from camelot.py _TIDAL_KEY_MAP).
const TIDAL_KEY_MAP: Record<string, string> = {
  csharp: 'c#', dsharp: 'd#', esharp: 'f', fsharp: 'f#', gsharp: 'g#',
  asharp: 'a#', bsharp: 'c', cflat: 'b', dflat: 'db', eflat: 'eb',
  fflat: 'e', gflat: 'gb', aflat: 'ab', bflat: 'bb',
};

function normalizeBareKey(keyStr: string): string | null {
  const lowered = keyStr.toLowerCase().trim();
  if (lowered in TIDAL_KEY_MAP) return `${TIDAL_KEY_MAP[lowered]} major`;
  if (lowered.length >= 1 && 'abcdefg'.includes(lowered[0])) {
    const rest = lowered.slice(1);
    if (rest === '' || rest === 'b' || rest === '#') {
      const note = keyStr[0].toUpperCase() + rest;
      return `${note} major`;
    }
  }
  return null;
}

export function parseCamelotKey(key: string | null | undefined): CamelotPosition | null {
  if (!key || !key.trim()) return null;
  const normalized = key.trim().toLowerCase();

  const direct = CAMELOT_MAP.get(normalized);
  if (direct) return direct;

  const compressed = normalized.replace(/\s+/g, ' ');
  const compressedHit = CAMELOT_MAP.get(compressed);
  if (compressedHit) return compressedHit;

  const stripped = normalized.replace(/\s/g, '');
  if (stripped.length >= 2 && (stripped.endsWith('a') || stripped.endsWith('b'))) {
    const numPart = stripped.slice(0, -1);
    if (/^\d+$/.test(numPart)) {
      const num = parseInt(numPart, 10);
      if (num >= 1 && num <= 12) return { number: num, letter: stripped.slice(-1).toUpperCase() };
    }
  }

  const bare = normalizeBareKey(key.trim());
  if (bare) {
    const bareHit = CAMELOT_MAP.get(bare.toLowerCase());
    if (bareHit) return bareHit;
  }
  return null;
}

export function camelotOrdinal(key: string | null | undefined): number | null {
  const pos = parseCamelotKey(key);
  if (!pos) return null;
  return pos.number * 2 + (pos.letter === 'B' ? 1 : 0);
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd dashboard && npx vitest run lib/__tests__/camelot.test.ts`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
cd /home/adam/github/WrzDJ/.worktrees/feat/issue-489
git checkout next-env.d.ts 2>/dev/null || true
git add dashboard/lib/camelot.ts dashboard/lib/__tests__/camelot.test.ts
git commit -m "feat(dashboard): add parity-complete Camelot key→ordinal helper (#489)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `request-sort.ts` — comparators, status counts, filter

**Files:**
- Modify: `dashboard/lib/request-sort.ts` (append; keep all existing exports)
- Test: `dashboard/lib/__tests__/request-sort.test.ts` (create if absent, else extend)

**Interfaces:**
- Consumes: `camelotOrdinal` from Task 1; existing `RequestSort`/`SortDirection` from `./api-types`; existing `SORT_FIELD_DEFAULT_DIRECTION`.
- Produces:
  - `export interface SortableRequestRow { id: number; created_at: string; accepted_at?: string | null; vote_count: number; bpm?: number | null; musical_key?: string | null; song_title: string; artist: string; status: string }`
  - `export type ClientSortField = Exclude<RequestSort, 'best_match'>` (the 7 client-sortable fields; `key` included).
  - `export function sortRequests<T extends SortableRequestRow>(rows: readonly T[], field: ClientSortField, direction: SortDirection): T[]` — pure, returns a new array.
  - `export function computeStatusCounts(rows: readonly SortableRequestRow[]): Record<StatusFilter, number>` — counts per status + `all`.
  - `export function filterByStatus<T extends SortableRequestRow>(rows: readonly T[], filter: StatusFilter): T[]` — `'all'` returns all.
- Import `StatusFilter` type from `@/app/(dj)/events/[code]/components/types` — **verify the import path resolves** (it is `../app/(dj)/events/[code]/components/types` relative to `lib/`). If a path alias `@/` is configured (it is, per existing imports), use `import type { StatusFilter } from '@/app/(dj)/events/[code]/components/types'`.

**Parity notes (must mirror `request_sort.py`):**
- `created_at`/`accepted_at` compared as `Date.parse` (ISO) numbers; `accepted_at` nullable → nulls last both directions.
- `vote_count` numeric.
- `bpm` nullable numeric → nulls last both directions.
- `title`/`artist` → `(x ?? '').toLowerCase()` localeCompare-free simple `<`/`>` to match Python's `func.lower` byte-ish ordering; use `< / >` on lowercased strings (NOT `localeCompare`, which differs from SQL `lower()` ordering). Tie-break `id DESC`.
- `key` → tuple `(isNull, signedOrdinal, title.toLowerCase, artist.toLowerCase, -id)` exactly like `key_sorted`. `signedOrdinal = desc ? -ordinal : ordinal` (0 when null — the `isNull` flag already forces nulls last).
- Every comparator ends with `id DESC` (`b.id - a.id`).

- [ ] **Step 1: Write the failing tests**

```typescript
// dashboard/lib/__tests__/request-sort.test.ts  (add to existing file if present)
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
    const rows = [row({ id: 1, vote_count: 5 }), row({ id: 2, vote_count: 5 }), row({ id: 3, vote_count: 9 })];
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
  it('title asc case-insensitive', () => {
    const rows = [row({ id: 1, song_title: 'banana' }), row({ id: 2, song_title: 'Apple' }), row({ id: 3, song_title: 'cherry' })];
    expect(sortRequests(rows, 'title', 'asc').map((r) => r.id)).toEqual([2, 1, 3]);
  });
  it('key asc by Camelot ordinal, nulls last, then title/artist/-id', () => {
    const rows = [
      row({ id: 1, musical_key: '8A' }),  // ord 16
      row({ id: 2, musical_key: null }),
      row({ id: 3, musical_key: '1A' }),  // ord 2
    ];
    expect(sortRequests(rows, 'key', 'asc').map((r) => r.id)).toEqual([3, 1, 2]);
    expect(sortRequests(rows, 'key', 'desc').map((r) => r.id)).toEqual([1, 3, 2]);
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
    const rows = [row({ id: 1, status: 'new' }), row({ id: 2, status: 'new' }), row({ id: 3, status: 'accepted' })];
    const c = computeStatusCounts(rows);
    expect(c.all).toBe(3);
    expect(c.new).toBe(2);
    expect(c.accepted).toBe(1);
    expect(c.playing).toBe(0);
  });
});

describe('filterByStatus', () => {
  it('all returns everything; specific filters', () => {
    const rows = [row({ id: 1, status: 'new' }), row({ id: 2, status: 'accepted' })];
    expect(filterByStatus(rows, 'all').map((r) => r.id)).toEqual([1, 2]);
    expect(filterByStatus(rows, 'accepted').map((r) => r.id)).toEqual([2]);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd dashboard && npx vitest run lib/__tests__/request-sort.test.ts`
Expected: FAIL — `sortRequests`/`computeStatusCounts`/`filterByStatus` not exported.

- [ ] **Step 3: Implement (append to `request-sort.ts`)**

```typescript
import { camelotOrdinal } from './camelot';
import type { StatusFilter } from '@/app/(dj)/events/[code]/components/types';

/** Minimal structural row both SongRequest (main) and PendingReviewRow share. */
export interface SortableRequestRow {
  id: number;
  created_at: string;
  accepted_at?: string | null;
  vote_count: number;
  bpm?: number | null;
  musical_key?: string | null;
  song_title: string;
  artist: string;
  status: string;
}

/** The 7 fields sortable entirely client-side (everything except best_match). */
export type ClientSortField = Exclude<RequestSort, 'best_match'>;

const ts = (iso: string | null | undefined): number | null =>
  iso ? Date.parse(iso) : null;

/** Nulls-last numeric compare for a given direction (mirrors SQL nullslast). */
function compareNullableNumber(a: number | null, b: number | null, desc: boolean): number {
  const aNull = a === null;
  const bNull = b === null;
  if (aNull && bNull) return 0;
  if (aNull) return 1; // nulls last
  if (bNull) return -1;
  return desc ? b - a : a - b;
}

function compareString(a: string, b: string, desc: boolean): number {
  const x = a.toLowerCase();
  const y = b.toLowerCase();
  if (x === y) return 0;
  const cmp = x < y ? -1 : 1;
  return desc ? -cmp : cmp;
}

/** Pure comparator mirroring server/app/services/request_sort.py for one field. */
function comparator(field: ClientSortField, direction: SortDirection) {
  const desc = direction === 'desc';
  const idTieBreak = (a: SortableRequestRow, b: SortableRequestRow) => b.id - a.id; // id DESC
  return (a: SortableRequestRow, b: SortableRequestRow): number => {
    let primary = 0;
    switch (field) {
      case 'date_requested':
        primary = compareNullableNumber(ts(a.created_at), ts(b.created_at), desc);
        break;
      case 'date_accepted':
        primary = compareNullableNumber(ts(a.accepted_at ?? null), ts(b.accepted_at ?? null), desc);
        break;
      case 'upvotes':
        primary = desc ? b.vote_count - a.vote_count : a.vote_count - b.vote_count;
        break;
      case 'bpm':
        primary = compareNullableNumber(a.bpm ?? null, b.bpm ?? null, desc);
        break;
      case 'title':
        primary = compareString(a.song_title, b.song_title, desc);
        break;
      case 'artist':
        primary = compareString(a.artist, b.artist, desc);
        break;
      case 'key': {
        const oa = camelotOrdinal(a.musical_key);
        const ob = camelotOrdinal(b.musical_key);
        primary = compareNullableNumber(oa, ob, desc);
        if (primary === 0) {
          primary = compareString(a.song_title, b.song_title, false);
          if (primary === 0) primary = compareString(a.artist, b.artist, false);
        }
        break;
      }
    }
    return primary !== 0 ? primary : idTieBreak(a, b);
  };
}

/** Sort rows client-side for a simple field. Returns a new array (no mutation). */
export function sortRequests<T extends SortableRequestRow>(
  rows: readonly T[],
  field: ClientSortField,
  direction: SortDirection,
): T[] {
  return [...rows].sort(comparator(field, direction));
}

const EMPTY_COUNTS: Record<StatusFilter, number> = {
  all: 0, new: 0, accepted: 0, playing: 0, played: 0, rejected: 0,
};

/** Per-status counts (+ all) from the in-memory set — correct by construction. */
export function computeStatusCounts(rows: readonly SortableRequestRow[]): Record<StatusFilter, number> {
  const counts: Record<StatusFilter, number> = { ...EMPTY_COUNTS };
  for (const r of rows) {
    counts.all += 1;
    if (r.status in counts && r.status !== 'all') {
      counts[r.status as StatusFilter] += 1;
    }
  }
  return counts;
}

/** Filter rows by status tab; 'all' returns the full set. */
export function filterByStatus<T extends SortableRequestRow>(
  rows: readonly T[],
  filter: StatusFilter,
): T[] {
  if (filter === 'all') return [...rows];
  return rows.filter((r) => r.status === filter);
}
```

> **Note on `key` tie-break direction:** the server's `key_sorted` uses `title.lower()` then `artist.lower()` ascending regardless of direction, then `-id` (id DESC). The code above passes `false` (ascending) for the title/artist secondary compares to match that exactly.

- [ ] **Step 4: Run to verify pass**

Run: `cd dashboard && npx vitest run lib/__tests__/request-sort.test.ts`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
cd /home/adam/github/WrzDJ/.worktrees/feat/issue-489
git checkout next-env.d.ts 2>/dev/null || true
git add dashboard/lib/request-sort.ts dashboard/lib/__tests__/request-sort.test.ts
git commit -m "feat(dashboard): add client-side request comparators + status helpers (#489)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `load-all-pages.ts` — chunked loader to the 2000 cap

**Files:**
- Create: `dashboard/lib/load-all-pages.ts`
- Test: `dashboard/lib/__tests__/load-all-pages.test.ts`

**Interfaces:**
- Consumes: `PUBLIC_PAGE_MAX` (= 500) from `@/lib/api`.
- Produces:
  - `export const REQUEST_LOAD_CAP = 2000;`
  - `export interface PageFetchResult<T> { requests: T[]; total: number }`
  - `export type PageFetcher<T> = (opts: { limit: number; offset: number; signal?: AbortSignal }) => Promise<PageFetchResult<T>>`
  - `export interface LoadAllResult<T> { requests: T[]; total: number; capped: boolean }`
  - `export async function loadAllPages<T>(fetcher: PageFetcher<T>, opts?: { signal?: AbortSignal }): Promise<LoadAllResult<T>>`

**Behavior:**
- Page from `offset 0` in `PUBLIC_PAGE_MAX` chunks. After the first page, `total` is known; keep fetching until `requests.length >= min(total, REQUEST_LOAD_CAP)`.
- `capped = total > REQUEST_LOAD_CAP`. When capped, stop at exactly `REQUEST_LOAD_CAP` rows (slice if a final chunk overshoots).
- Honor `opts.signal`: if aborted between/within chunks, reject with the abort reason (pass `signal` down to the fetcher).
- Guard against a server returning fewer rows than `limit` while `total` claims more (broken pagination): if a chunk returns 0 rows, stop to avoid an infinite loop.

- [ ] **Step 1: Write the failing tests**

```typescript
// dashboard/lib/__tests__/load-all-pages.test.ts
import { describe, it, expect, vi } from 'vitest';
import { loadAllPages, REQUEST_LOAD_CAP, type PageFetcher } from '../load-all-pages';

// Build a fetcher over a fixed-size virtual dataset using PUBLIC_PAGE_MAX=500.
function makeFetcher(total: number): PageFetcher<{ id: number }> {
  return vi.fn(async ({ limit, offset }) => ({
    total,
    requests: Array.from(
      { length: Math.max(0, Math.min(limit, total - offset)) },
      (_, i) => ({ id: offset + i }),
    ),
  }));
}

describe('loadAllPages', () => {
  it('returns a single short page without extra fetches', async () => {
    const fetcher = makeFetcher(30);
    const res = await loadAllPages(fetcher);
    expect(res.requests).toHaveLength(30);
    expect(res.total).toBe(30);
    expect(res.capped).toBe(false);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('stitches multiple 500-row pages up to total', async () => {
    const fetcher = makeFetcher(1200);
    const res = await loadAllPages(fetcher);
    expect(res.requests).toHaveLength(1200);
    expect(res.capped).toBe(false);
    expect(fetcher).toHaveBeenCalledTimes(3); // 500 + 500 + 200
  });

  it('caps at REQUEST_LOAD_CAP and flags capped', async () => {
    const fetcher = makeFetcher(5000);
    const res = await loadAllPages(fetcher);
    expect(res.requests).toHaveLength(REQUEST_LOAD_CAP);
    expect(res.total).toBe(5000);
    expect(res.capped).toBe(true);
  });

  it('aborts when the signal fires', async () => {
    const controller = new AbortController();
    const fetcher: PageFetcher<{ id: number }> = vi.fn(async () => {
      controller.abort();
      return { total: 5000, requests: Array.from({ length: 500 }, (_, i) => ({ id: i })) };
    });
    await expect(loadAllPages(fetcher, { signal: controller.signal })).rejects.toThrow();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd dashboard && npx vitest run lib/__tests__/load-all-pages.test.ts`
Expected: FAIL — `../load-all-pages` not found.

- [ ] **Step 3: Implement `load-all-pages.ts`**

```typescript
/**
 * Chunked "load the whole bounded set once" loader for the event request lists
 * (issue #489). Pages a {requests, total} fetcher PUBLIC_PAGE_MAX rows at a time
 * up to a 2000-row safety cap, so the browser can sort/filter/count in memory.
 */
import { PUBLIC_PAGE_MAX } from '@/lib/api';

/** Hard ceiling on rows loaded for in-memory sort/filter. */
export const REQUEST_LOAD_CAP = 2000;

export interface PageFetchResult<T> {
  requests: T[];
  total: number;
}

export type PageFetcher<T> = (opts: {
  limit: number;
  offset: number;
  signal?: AbortSignal;
}) => Promise<PageFetchResult<T>>;

export interface LoadAllResult<T> {
  requests: T[];
  total: number;
  capped: boolean;
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) {
    throw signal.reason instanceof Error
      ? signal.reason
      : new DOMException('Aborted', 'AbortError');
  }
}

export async function loadAllPages<T>(
  fetcher: PageFetcher<T>,
  opts?: { signal?: AbortSignal },
): Promise<LoadAllResult<T>> {
  const signal = opts?.signal;
  const acc: T[] = [];
  let total = 0;
  let offset = 0;

  // First fetch establishes `total`; loop until we reach the capped target.
  // eslint-disable-next-line no-constant-condition
  while (true) {
    throwIfAborted(signal);
    const page = await fetcher({ limit: PUBLIC_PAGE_MAX, offset, signal });
    throwIfAborted(signal);
    total = page.total;
    acc.push(...page.requests);
    offset += page.requests.length;

    const target = Math.min(total, REQUEST_LOAD_CAP);
    if (page.requests.length === 0) break; // broken pagination guard
    if (acc.length >= target) break;
  }

  const capped = total > REQUEST_LOAD_CAP;
  const requests = capped ? acc.slice(0, REQUEST_LOAD_CAP) : acc;
  return { requests, total, capped };
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd dashboard && npx vitest run lib/__tests__/load-all-pages.test.ts`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
cd /home/adam/github/WrzDJ/.worktrees/feat/issue-489
git checkout next-env.d.ts 2>/dev/null || true
git add dashboard/lib/load-all-pages.ts dashboard/lib/__tests__/load-all-pages.test.ts
git commit -m "feat(dashboard): add chunked load-all-pages loader with 2000 cap (#489)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `use-event-requests.ts` — main-queue orchestration hook

**Files:**
- Create: `dashboard/lib/use-event-requests.ts`
- Test: `dashboard/lib/__tests__/use-event-requests.test.ts`

**Interfaces:**
- Consumes: `loadAllPages`, `REQUEST_LOAD_CAP`, `PageFetchResult` (Task 3); `sortRequests`, `filterByStatus`, `computeStatusCounts`, `ClientSortField` (Task 2); `api`/`SongRequest`/`RequestListResponse` from `@/lib/api`; `RequestSort`/`SortDirection` from `@/lib/api-types`; `StatusFilter` from the components/types.
- Produces a hook:

```typescript
export interface UseEventRequestsResult {
  /** Full loaded set (already capped), unsorted/unfiltered — source of truth. */
  allRequests: SongRequest[];
  /** Derived view: filtered by status then sorted (client) or server-ordered (best_match). */
  visibleRequests: SongRequest[];
  total: number;          // in-memory total when not capped; server total when capped
  capped: boolean;
  statusCounts: Record<StatusFilter, number>;
  loading: boolean;
  error: string | null;
  /** Replace the full set (used by initial loadData merge). */
  setAllRequests: React.Dispatch<React.SetStateAction<SongRequest[]>>;
  /** Force a coalesced refetch now (used after mutations / status change). */
  refetch: () => void;
  /** Schedule a debounced refetch (used by SSE). */
  scheduleRefetch: () => void;
}

export function useEventRequests(params: {
  code: string;
  enabled: boolean;
  sortField: RequestSort;
  sortDirection: SortDirection;
  statusFilter: StatusFilter;
}): UseEventRequestsResult;
```

**Behavior:**
- **Network refetch triggers ONLY on `code`/`enabled` change and the `best_match` ↔ simple-field boundary** (server order vs client order needs a re-fetch). `sortDirection` and `statusFilter` changes — and simple-field → simple-field changes — are **client-side-only**: they re-derive `visibleRequests`/`statusCounts` via `filterByStatus`/`sortRequests` in a `useMemo` with **no** `loadAllPages` call. This is the instant-sort UX win; routing those through a fetch would undo it. When a load does run, it starts a (debounced-immediate) `loadAllPages` via a fetcher built from `api.getRequests`. For `best_match`, pass `sort: 'best_match'` and DO NOT client-resort (render server order). For the 7 simple fields, fetch with NO `sort` (server default `date_requested DESC`, for stable chunk stitching), then `sortRequests` in memory.
- `visibleRequests`: `filterByStatus(allRequests, statusFilter)` then, if `sortField !== 'best_match'`, `sortRequests(filtered, sortField as ClientSortField, sortDirection)`; else the filtered slice in server order.
- `statusCounts`/`total`: when not capped, from `allRequests` (`computeStatusCounts`, `allRequests.length`); when capped, `total` is the server total and a banner is shown (counts still from the loaded 2000 — acceptable per design; document it).
- `scheduleRefetch`: ~500ms debounce that collapses a burst into one `loadAllPages`. `refetch`: immediate.
- `AbortController`: each new load aborts the previous in-flight load (sort/status/refetch change). Aborted loads must not commit state.
- Status filter passed to the server fetcher so the loaded set is already the active filter's rows — counts for the *other* tabs then come from… **wait:** counts must cover ALL statuses. **Decision:** fetch the FULL event (no status filter) so `computeStatusCounts` is correct across tabs, and apply the status filter client-side via `filterByStatus`. This matches the design's "counts correct by construction". The 2000 cap then applies to the whole event.

> Implementer: prefer the second decision — **load the full event unfiltered, filter client-side.** This is what makes counts correct by construction and is the design's intent.

- [ ] **Step 1: Write the failing tests** (fake timers; mock `api.getRequests`)

```typescript
// dashboard/lib/__tests__/use-event-requests.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useEventRequests } from '../use-event-requests';
import { api } from '@/lib/api';

vi.mock('@/lib/api', async (orig) => {
  const actual = await orig<typeof import('@/lib/api')>();
  return { ...actual, api: { ...actual.api, getRequests: vi.fn() } };
});

function mockList(ids: number[], total = ids.length) {
  return {
    requests: ids.map((id) => ({
      id, created_at: '2026-01-01T00:00:00Z', accepted_at: null, vote_count: id,
      bpm: null, musical_key: null, song_title: `s${id}`, artist: `a${id}`,
      status: 'new', event_id: 1, genre: null, is_duplicate: false, nickname: null,
      note: null, priority_score: null, raw_search_query: null, source: 'manual',
      source_url: null, artwork_url: null, sync_results_json: null,
      updated_at: '2026-01-01T00:00:00Z',
    })),
    total, limit: 500, offset: 0, sort: 'date_requested', direction: 'desc',
    status_counts: { all: total, new: total, accepted: 0, playing: 0, played: 0, rejected: 0 },
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(api.getRequests).mockResolvedValue(mockList([3, 2, 1]) as never);
});
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks(); });

describe('useEventRequests', () => {
  it('loads the full set and sorts client-side for a simple field', async () => {
    const { result } = renderHook(() =>
      useEventRequests({ code: 'EVT', enabled: true, sortField: 'upvotes', sortDirection: 'desc', statusFilter: 'all' }),
    );
    await act(async () => { await vi.runAllTimersAsync(); });
    await waitFor(() => expect(result.current.allRequests).toHaveLength(3));
    expect(result.current.visibleRequests.map((r) => r.id)).toEqual([3, 2, 1]);
    expect(result.current.statusCounts.all).toBe(3);
  });

  it('coalesces a burst of scheduleRefetch into ONE load', async () => {
    const { result } = renderHook(() =>
      useEventRequests({ code: 'EVT', enabled: true, sortField: 'date_requested', sortDirection: 'desc', statusFilter: 'all' }),
    );
    await act(async () => { await vi.runAllTimersAsync(); });
    vi.mocked(api.getRequests).mockClear();
    act(() => { result.current.scheduleRefetch(); result.current.scheduleRefetch(); result.current.scheduleRefetch(); });
    await act(async () => { await vi.runAllTimersAsync(); });
    expect(api.getRequests).toHaveBeenCalledTimes(1);
  });

  it('does not client re-sort best_match (renders server order)', async () => {
    vi.mocked(api.getRequests).mockResolvedValue(mockList([1, 3, 2]) as never); // server order
    const { result } = renderHook(() =>
      useEventRequests({ code: 'EVT', enabled: true, sortField: 'best_match', sortDirection: 'desc', statusFilter: 'all' }),
    );
    await act(async () => { await vi.runAllTimersAsync(); });
    await waitFor(() => expect(result.current.allRequests).toHaveLength(3));
    expect(result.current.visibleRequests.map((r) => r.id)).toEqual([1, 3, 2]);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd dashboard && npx vitest run lib/__tests__/use-event-requests.test.ts`
Expected: FAIL — `../use-event-requests` not found.

- [ ] **Step 3: Implement `use-event-requests.ts`**

Build the fetcher from `api.getRequests` mapping its envelope to `PageFetchResult`. Load the FULL event unfiltered. Use `useMemo` for `visibleRequests`/`statusCounts`. Use a `useRef<AbortController>` and a `useRef` debounce timer. Skeleton:

```typescript
'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, SongRequest } from '@/lib/api';
import type { RequestSort, SortDirection } from '@/lib/api-types';
import type { StatusFilter } from '@/app/(dj)/events/[code]/components/types';
import { loadAllPages, type PageFetcher } from './load-all-pages';
import {
  sortRequests, filterByStatus, computeStatusCounts, type ClientSortField,
} from './request-sort';

const REFETCH_DEBOUNCE_MS = 500;

export interface UseEventRequestsResult {
  allRequests: SongRequest[];
  visibleRequests: SongRequest[];
  total: number;
  capped: boolean;
  statusCounts: Record<StatusFilter, number>;
  loading: boolean;
  error: string | null;
  setAllRequests: React.Dispatch<React.SetStateAction<SongRequest[]>>;
  refetch: () => void;
  scheduleRefetch: () => void;
}

export function useEventRequests(params: {
  code: string;
  enabled: boolean;
  sortField: RequestSort;
  sortDirection: SortDirection;
  statusFilter: StatusFilter;
}): UseEventRequestsResult {
  const { code, enabled, sortField, sortDirection, statusFilter } = params;

  const [allRequests, setAllRequests] = useState<SongRequest[]>([]);
  const [serverTotal, setServerTotal] = useState(0);
  const [capped, setCapped] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // best_match must be fetched in server order; simple fields fetch the default
  // order then sort in memory. Keep the live sortField in a ref for the fetcher.
  const sortFieldRef = useRef(sortField);
  sortFieldRef.current = sortField;

  const runLoad = useCallback(async () => {
    if (!enabled) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    const isBestMatch = sortFieldRef.current === 'best_match';
    const fetcher: PageFetcher<SongRequest> = async ({ limit, offset, signal }) => {
      const resp = await api.getRequests(code, {
        // Full event (no status filter) so counts are correct across tabs.
        sort: isBestMatch ? 'best_match' : 'date_requested',
        direction: isBestMatch ? 'desc' : 'desc',
        limit, offset,
        // api.getRequests does not currently forward an AbortSignal; if it gains
        // one, pass `signal` here. For now we guard via throwIfAborted in loader.
      });
      void signal;
      return { requests: resp.requests, total: resp.total };
    };
    try {
      const res = await loadAllPages(fetcher, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setAllRequests(res.requests);
      setServerTotal(res.total);
      setCapped(res.capped);
      setError(null);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : 'Failed to load requests');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [code, enabled]);

  const refetch = useCallback(() => { void runLoad(); }, [runLoad]);

  const scheduleRefetch = useCallback(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => { void runLoad(); }, REFETCH_DEBOUNCE_MS);
  }, [runLoad]);

  // Reload when code/enabled changes or sortField flips between best_match and a
  // simple field (server-order vs client-order needs a refetch). Simple→simple
  // and direction-only changes are handled purely in-memory by the memo below.
  const needsServerOrder = sortField === 'best_match';
  useEffect(() => {
    void runLoad();
    return () => { abortRef.current?.abort(); if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [runLoad, needsServerOrder]);

  const visibleRequests = useMemo(() => {
    const filtered = filterByStatus(allRequests, statusFilter);
    if (sortField === 'best_match') return filtered; // server order
    return sortRequests(filtered, sortField as ClientSortField, sortDirection);
  }, [allRequests, statusFilter, sortField, sortDirection]);

  const statusCounts = useMemo(() => computeStatusCounts(allRequests), [allRequests]);
  const total = capped ? serverTotal : allRequests.length;

  return {
    allRequests, visibleRequests, total, capped, statusCounts, loading, error,
    setAllRequests, refetch, scheduleRefetch,
  };
}
```

> Implementer notes:
> - The status filter and direction and simple-field changes are **memo-only** (no refetch) — that is the instant-UX win. Only `best_match ↔ simple` toggles refetch (server order vs client order). `code`/`enabled` also refetch.
> - `api.getRequests` has no `signal` param today; do NOT add one (frontend-only-to-this-slice; changing the api signature risks #506 collision). The loader's `throwIfAborted` + the `controller.signal.aborted` commit-guards prevent stale writes; that satisfies the abort test.
> - For the coalesce test: `scheduleRefetch` debounces; the burst collapses to one `runLoad`.

- [ ] **Step 4: Run to verify pass**

Run: `cd dashboard && npx vitest run lib/__tests__/use-event-requests.test.ts`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
cd /home/adam/github/WrzDJ/.worktrees/feat/issue-489
git checkout next-env.d.ts 2>/dev/null || true
git add dashboard/lib/use-event-requests.ts dashboard/lib/__tests__/use-event-requests.test.ts
git commit -m "feat(dashboard): add useEventRequests hook (load-all + coalesced SSE refetch) (#489)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `RequestQueueSection` — cap banner; "Load More" auto-hides

**Files:**
- Modify: `dashboard/app/(dj)/events/[code]/components/RequestQueueSection.tsx`
- Test: `dashboard/app/(dj)/events/[code]/components/__tests__/RequestQueueSection.test.tsx` (extend)

**Interfaces:**
- Consumes: existing props. Add **optional** `capped?: boolean` (default `undefined`/false). Keep `onLoadMore`/`total` props so the component contract and #506-adjacent files don't break; in client-side mode `requests.length === total` so "Load More" never renders (no behavior change needed in its conditional). When `capped`, render the banner.

- [ ] **Step 1: Write the failing test** (extend the existing describe)

```typescript
it('shows the cap banner when capped', () => {
  render(
    <RequestQueueSection
      {...baseProps}                       // reuse the file's existing prop builder
      requests={baseProps.requests}
      total={5000}
      capped
    />,
  );
  expect(screen.getByText(/Showing 2000 of 5000 requests/i)).toBeInTheDocument();
  expect(screen.getByText(/sort\/filter limited to these/i)).toBeInTheDocument();
});
```

> If the test file lacks a reusable `baseProps`, construct minimal props inline (mirror the existing tests in that file). The banner copy MUST be: `Showing 2000 of {total} requests — sort/filter limited to these.`

- [ ] **Step 2: Run to verify failure**

Run: `cd dashboard && npx vitest run "app/(dj)/events/[code]/components/__tests__/RequestQueueSection.test.tsx"`
Expected: FAIL — banner text absent.

- [ ] **Step 3: Implement**

Add to the props interface (after `statusCounts`):

```typescript
  /** True when the event exceeds the 2000-row in-memory cap (issue #489). */
  capped?: boolean;
```

Add `capped` to the destructured params. Render the banner just above the "Showing X of Y" block (inside the same trailing region, before the IIFE or right after it):

```tsx
{capped && (
  <div
    role="status"
    style={{
      padding: '0.625rem 0.875rem',
      marginBottom: '0.75rem',
      background: 'var(--surface-raised)',
      border: '1px solid var(--border)',
      borderRadius: 8,
      fontSize: '0.8rem',
      color: 'var(--text-secondary)',
    }}
  >
    Showing 2000 of {total} requests — sort/filter limited to these.
  </div>
)}
```

> The existing "Load More" conditional (`loaded < total && loaded < PUBLIC_PAGE_MAX`) stays. In client-side mode the page now passes the full set, so `loaded === total` → it never shows. No removal needed (keeps the expired/archived path and #506 safe). `REQUEST_LOAD_CAP` (2000) is hard-coded in the banner copy per the design's fixed wording.

- [ ] **Step 4: Run to verify pass**

Run: `cd dashboard && npx vitest run "app/(dj)/events/[code]/components/__tests__/RequestQueueSection.test.tsx"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/adam/github/WrzDJ/.worktrees/feat/issue-489
git checkout next-env.d.ts 2>/dev/null || true
git add "dashboard/app/(dj)/events/[code]/components/RequestQueueSection.tsx" "dashboard/app/(dj)/events/[code]/components/__tests__/RequestQueueSection.test.tsx"
git commit -m "feat(dashboard): add cap banner to RequestQueueSection (#489)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `page.tsx` — swap the request-store slice for the hook

**Files:**
- Modify: `dashboard/app/(dj)/events/[code]/page.tsx`
- Test: `dashboard/app/(dj)/events/[code]/__tests__/page.test.tsx` (extend/adjust)

**Interfaces:**
- Consumes: `useEventRequests` (Task 4), `RequestQueueSection` `capped` prop (Task 5).

**Surgical change set (touch ONLY the request-store slice):**
1. Add import: `import { useEventRequests } from '@/lib/use-event-requests';`.
2. Replace these states/refs/callbacks with the hook:
   - Remove: `requests`/`setRequests` (line 73), `INITIAL_DISPLAY_LIMIT`/`displayLimit`/`setDisplayLimit` (76-77), `requestTotal`/`setRequestTotal` (78), `statusCounts`/`setStatusCounts` (83-85), `displayLimitRef` (226-227), the `reloadRequests` callback (240-255), the `handleLoadMore` callback (963-969), and the sort-change refetch effect (484-493).
   - Keep: `statusFilter`/`setStatusFilter` + `statusFilterRef`, `sortField`/`sortDirection` + their refs and handlers (these feed the hook), `normalizeStatusCounts` is no longer needed for the queue (hook computes counts) — but `loadData`'s other consumers may still use `status_counts`; verify and remove only the queue usage.
3. Instantiate the hook near the other request state:

```typescript
const {
  visibleRequests,
  total: requestTotal,
  capped: requestsCapped,
  statusCounts,
  setAllRequests,
  refetch: refetchRequests,
  scheduleRefetch: scheduleRequestsRefetch,
} = useEventRequests({
  code,
  enabled: isAuthenticated,
  sortField,
  sortDirection,
  statusFilter,
});
```

4. Replace all `requests` reads passed to children with `visibleRequests`. Replace optimistic `setRequests((prev) => …)` calls (lines 518, 715, 892, 904) with `setAllRequests((prev) => …)` (same updater shape — the hook's memo re-derives the visible view). 
5. `loadData` (361-476): it fetches `api.getRequests` as part of its `Promise.all`. **Decision:** stop committing the queue from `loadData` — instead, after the event loads, the hook owns the queue. Remove the `api.getRequests` call from `loadData`'s `Promise.all` and the `setRequests`/`setRequestTotal`/`setStatusCounts` lines (382-384, 448-450). The hook loads the queue on mount (it's `enabled` once authenticated). Keep the rest of `loadData` (event, display settings, tidal/beatport, live-display hop) intact. The 5s `usePollingLoop(loadData)` then no longer refetches the queue — that's fine; SSE + `scheduleRequestsRefetch` keep it live (and the poll still refreshes event/bridge/now-playing).
   - **Important:** to preserve the existing "queue stays fresh on the 5s cadence even without SSE" safety net, add `scheduleRequestsRefetch()` inside `loadData` (or a small interval) is NOT needed — but to be safe and match prior behavior, call `refetchRequests()` is also not needed each poll. Keep it simple: rely on SSE coalesced refetch (design's explicit choice). Do not re-add polling for the queue.
6. SSE wiring (498-512): add `onRequestStatusChanged` and `onRequestsBulkUpdate` handlers; route all request-affecting events through `scheduleRequestsRefetch()` instead of `loadDataRef.current()`. Keep `onNowPlayingChanged`/`onBridgeStatusChanged` calling `loadDataRef.current()` (they refresh non-queue state) but ALSO `scheduleRequestsRefetch()` on `onNowPlayingChanged` (best_match order can shift). Concretely:

```typescript
useEventStream(isAuthenticated ? code : null, {
  onRequestCreated: () => { scheduleRequestsRefetch(); },
  onRequestStatusChanged: () => { scheduleRequestsRefetch(); },
  onRequestsBulkUpdate: () => { scheduleRequestsRefetch(); },
  onNowPlayingChanged: () => { scheduleRequestsRefetch(); loadDataRef.current(); },
  onBridgeStatusChanged: (data) => { /* keep existing bridge state set */ loadDataRef.current(); },
});
```

7. Mutations that previously called `await reloadRequests()` (handleRejectAll 920, handleBulkDelete 931, handleAcceptRecommendedTrack 954, handleRefreshRequests 958, handleFilterChange 266) → call `refetchRequests()`. `handleFilterChange` (260-271): now purely sets `statusFilter` (memo re-filters instantly — no fetch); drop the `reloadRequests` call and `displayLimit` reset. Keep the `localStorage`/ref bookkeeping for sort, but `displayLimit` bookkeeping is gone.
8. Pass `capped={requestsCapped}` to both `RequestQueueSection` (1142) and `SongManagementTab` (1204) — verify `SongManagementTab` forwards `capped` to its inner `RequestQueueSection`; if it renders one, thread the prop through (Task 5 made it optional, so an un-threaded path still compiles).

> The implementer MUST grep for every remaining reference to the removed identifiers (`setRequests`, `requestTotal`, `displayLimit`, `setStatusCounts`, `reloadRequests`, `handleLoadMore`, `requests` as the raw list) and reconcile each. `npx tsc --noEmit` is the gate.

- [ ] **Step 1: Adjust the existing page test expectations**

`page.test.tsx` mocks `api.getRequests` and currently asserts via the mocked `RequestQueueSection`. Update its mock so `api.getRequests` is still called (now by the hook, not `loadData`) and the mocked section receives `visibleRequests`. Add a focused test:

```typescript
it('renders requests loaded by the hook and counts from memory', async () => {
  vi.mocked(api.getRequests).mockResolvedValue(
    mockRequestList([
      // two rows; helper builds the #478 envelope
    ] as never),
  );
  // render page, wait for the mocked RequestQueueSection to receive rows
});
```

> Keep the test pragmatic: the heavy sort/hook logic is already unit-tested in Tasks 1-4. Here, assert the page wires the hook (requests render, no crash, filter tab switch doesn't trigger a new `getRequests` call).

- [ ] **Step 2: Run to verify failure**

Run: `cd dashboard && npx vitest run "app/(dj)/events/[code]/__tests__/page.test.tsx"`
Expected: FAIL (or red on the new assertion) before the refactor.

- [ ] **Step 3: Implement the surgical refactor** (per the change set above)

- [ ] **Step 4: Run the full type-check + page tests**

Run: `cd dashboard && npx tsc --noEmit && npx vitest run "app/(dj)/events/[code]/__tests__/page.test.tsx"`
Expected: tsc clean; page tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/adam/github/WrzDJ/.worktrees/feat/issue-489
git checkout next-env.d.ts 2>/dev/null || true
git add "dashboard/app/(dj)/events/[code]/page.tsx" "dashboard/app/(dj)/events/[code]/__tests__/page.test.tsx"
git commit -m "feat(dashboard): main queue uses client-side useEventRequests hook (#489)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `PreEventVotingTab` — compose helpers, load-all, drop "Load More"

**Files:**
- Modify: `dashboard/app/(dj)/events/[code]/components/PreEventVotingTab.tsx`
- Test: `dashboard/app/(dj)/events/[code]/components/__tests__/PreEventVotingTab.test.tsx` (modify fixtures + assertions)

**Interfaces:**
- Consumes: `loadAllPages`/`REQUEST_LOAD_CAP` (Task 3); `sortRequests`/`filterByStatus`(unused — all pending are `new`)/`ClientSortField` (Task 2); `toPendingReviewParams`/`REVIEW_ORDER`/`PendingReviewSort` (existing); `api.getPendingReview`/`PendingReviewRow` (existing).

**Change set:**
1. Replace the growing-window state (`displayLimit`, `loadingMore`, `loadMore`) with a load-all-to-cap model:
   - State: `pending: PendingReviewRow[]`, `pendingTotal: number`, `capped: boolean`, plus existing `selected`/sort state.
   - `fetchAll()`: build a `PageFetcher<PendingReviewRow>` from `api.getPendingReview` (map envelope → `{requests, total}`); call `loadAllPages`. For `review_order` (sentinel), fetch with NO sort (server order) and DO NOT client re-sort. For a simple field, fetch with NO sort (server default) then `sortRequests(rows, field, direction)` in memory. Set `pending`, `pendingTotal`, `capped`.
   - The `useEffect` deps stay `[event.code, sortField, sortDirection]` but now: for simple-field sort/direction changes, **re-sort in memory without refetch** (instant). Simplest correct structure: keep `allPending` (full loaded set) in state; derive the rendered `pending` via `useMemo` (review_order → server order as loaded; simple field → `sortRequests`). Refetch only on `event.code` change (and after bulk actions).
2. `review_order` is fetched in server order; simple fields sort in memory — mirror the main queue's split.
3. Drop the "Load More" button + `Showing X of Y` growing-window block; replace with a `Showing {pending.length} of {pendingTotal}` line and, when `capped`, the banner: `Showing 2000 of {pendingTotal} requests — sort/filter limited to these.`
4. `bulk(...)` and `refresh()` → call `fetchAll()` (full reload) after a bulk action.
5. Keep all the unrelated UI (collection settings, Tidal section, phase controls) byte-for-byte.

**Derivation skeleton:**

```typescript
const [allPending, setAllPending] = useState<PendingReviewRow[]>([]);
const [pendingTotal, setPendingTotal] = useState(0);
const [capped, setCapped] = useState(false);
const fetchSeqRef = useRef(0);

const fetchAll = useCallback(async () => {
  const seq = ++fetchSeqRef.current;
  const fetcher: PageFetcher<PendingReviewRow> = async ({ limit, offset }) => {
    const resp = await apiClient.getPendingReview(event.code, {
      ...toPendingReviewParams(sortField, sortDirection), // review_order → {}; field → server order for stable stitch? see note
      limit, offset,
    });
    return { requests: resp.requests, total: resp.total };
  };
  try {
    const res = await loadAllPages(fetcher);
    if (seq !== fetchSeqRef.current) return;
    setAllPending(res.requests);
    setPendingTotal(res.total);
    setCapped(res.capped);
  } catch { /* keep last-good set */ }
}, [event.code, sortField, sortDirection]);
```

> **Stitch-stability note:** chunked offset paging requires a stable server order across chunks. `review_order` and any single server field sort are stable. **Decision (mirror the main queue):** always fetch pending with NO sort param (server default `review_order`) for stable stitching, then in memory: `review_order` → render as loaded; simple field → `sortRequests`. This means `fetchAll` deps reduce to `[event.code]`; sort/direction become memo-only (instant). Update `fetchAll`'s fetcher to send `{}` (no sort) and move sorting into a `useMemo`.

**Final derivation:**

```typescript
const pending = useMemo(() => {
  if (sortField === REVIEW_ORDER) return allPending;          // server vote-rank order
  return sortRequests(allPending, sortField as ClientSortField, sortDirection);
}, [allPending, sortField, sortDirection]);
```

- [ ] **Step 1: Update the test fixtures + write failing assertions**

In `PreEventVotingTab.test.tsx`: ensure `getPendingReview` mock returns the envelope `{ requests, total, capped-less }`. Add/adjust:
  - sort a simple field (e.g. Title) → assert order changes WITHOUT a second `getPendingReview` call (instant client sort).
  - `review_order` selected → rows render in the server-provided order.
  - assert NO "Load More" button (`queryByText('Load More')` is null).
  - capped: mock `total = 5000`, fetcher returns 2000 → assert the banner text.

- [ ] **Step 2: Run to verify failure**

Run: `cd dashboard && npx vitest run "app/(dj)/events/[code]/components/__tests__/PreEventVotingTab.test.tsx"`
Expected: FAIL on the new assertions.

- [ ] **Step 3: Implement the refactor** (per change set; keep unrelated UI intact)

- [ ] **Step 4: Run to verify pass**

Run: `cd dashboard && npx vitest run "app/(dj)/events/[code]/components/__tests__/PreEventVotingTab.test.tsx"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/adam/github/WrzDJ/.worktrees/feat/issue-489
git checkout next-env.d.ts 2>/dev/null || true
git add "dashboard/app/(dj)/events/[code]/components/PreEventVotingTab.tsx" "dashboard/app/(dj)/events/[code]/components/__tests__/PreEventVotingTab.test.tsx"
git commit -m "feat(dashboard): pending-review tab uses client-side sort + load-all (#489)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Full CI green + finishing

**Files:** none (verification + PR).

- [ ] **Step 1: Lint**

Run: `cd dashboard && npm run lint`
Expected: no errors. Fix any.

- [ ] **Step 2: Type-check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Full test run + coverage**

Run: `cd dashboard && npm test -- --run`
Expected: all pass; coverage ≥ 68% br / 65% fn / 78% ln / 77% st. If a thinly-covered new file dips a metric, add a focused test (do not lower thresholds).

- [ ] **Step 4: Clean `next-env.d.ts`**

Run: `cd /home/adam/github/WrzDJ/.worktrees/feat/issue-489 && git checkout dashboard/next-env.d.ts 2>/dev/null || true; git status`
Expected: only intended files staged/clean.

- [ ] **Step 5: Finish** — invoke `superpowers:finishing-a-development-branch`, option 2 (Push + PR). PR title: `feat(dashboard): client-side sort/filter for both event-page request lists`. PR body: `Closes #489`, `## Why`, `## What`, `## Testing` tickable checkboxes, trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## Self-Review

**Spec coverage:**
- Both lists → client-side: Tasks 6 (main) + 7 (pending). ✓
- Shared pure helpers `camelot.ts`/`request-sort.ts`/`load-all-pages.ts` + thin `use-event-requests.ts`: Tasks 1-4. ✓
- Sort parity (id DESC, nulls-last both dirs, case-insensitive title/artist, key ordinal tuple): Task 2 + Task 1. ✓
- best_match (main) + review_order (pending) never client re-sorted: Tasks 4 + 7. ✓
- Coalesced ~500ms refetch on SSE, optimistic patches kept, abort on change: Tasks 4 + 6. ✓
- 2000 cap, 500-chunks, banner copy: Tasks 3 + 5 + 7. ✓
- Counts correct by construction (full event loaded, client filter): Tasks 2 + 4. ✓
- No backend/SSE/migration; kiosk + admin untouched: scope honored (no server files in any task). ✓
- Tests updated (PreEventVotingTab, page): Tasks 6 + 7. ✓
- Don't touch other ~60 page.tsx states: Task 6 is explicitly surgical. ✓

**Type consistency:** `sortRequests`/`computeStatusCounts`/`filterByStatus`/`SortableRequestRow`/`ClientSortField` (Task 2) used verbatim in Tasks 4 & 7. `loadAllPages`/`PageFetcher`/`REQUEST_LOAD_CAP`/`LoadAllResult` (Task 3) used verbatim in Tasks 4 & 7. `camelotOrdinal` (Task 1) used in Task 2. `capped` prop (Task 5) consumed in Task 6. Hook result fields (Task 4) consumed in Task 6.

**Placeholders:** none — every code step shows the code; banner copy is fixed verbatim.
