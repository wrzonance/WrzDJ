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
  // Minor keys (A ring)
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
  // Major keys (B ring) — no bare "BM"/"FM" (they collide with minor abbrevs).
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

// Build the lookup map once at module load.
const CAMELOT_MAP = new Map<string, CamelotPosition>();
for (const [num, letter, names] of KEY_DEFINITIONS) {
  const pos: CamelotPosition = { number: num, letter };
  CAMELOT_MAP.set(`${num}${letter}`, pos);
  CAMELOT_MAP.set(`${num}${letter.toLowerCase()}`, pos);
  for (const name of names) CAMELOT_MAP.set(name, pos);
}

// Tidal "CSharp"/"FSharp" → standard notation (from camelot.py _TIDAL_KEY_MAP).
const TIDAL_KEY_MAP: Record<string, string> = {
  csharp: 'c#',
  dsharp: 'd#',
  esharp: 'f',
  fsharp: 'f#',
  gsharp: 'g#',
  asharp: 'a#',
  bsharp: 'c',
  cflat: 'b',
  dflat: 'db',
  eflat: 'eb',
  fflat: 'e',
  gflat: 'gb',
  aflat: 'ab',
  bflat: 'bb',
};

/**
 * Convert a bare key name (no major/minor) to "X major" format.
 * Handles "Eb" → "Eb major", "CSharp" → "C# major", "G" → "G major".
 * Returns null if the string doesn't look like a bare key name.
 */
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

/**
 * Parse a musical key string into a Camelot wheel position.
 * Handles "A minor", "Am", "A min", "8A", "C maj", sharps/flats, Camelot codes,
 * and bare Tidal keys ("Eb", "G", "CSharp"). Returns null for unparseable input.
 */
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

/**
 * Map a key to a sortable harmonic ordinal: 1A=2, 1B=3, ... 12B=25.
 * Mirrors `_camelot_ordinal` in request_sort.py. Null/unparseable → null.
 */
export function camelotOrdinal(key: string | null | undefined): number | null {
  const pos = parseCamelotKey(key);
  if (!pos) return null;
  return pos.number * 2 + (pos.letter === 'B' ? 1 : 0);
}
