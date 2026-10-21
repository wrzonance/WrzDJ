"""Reusable musical key, tempo, and genre compatibility primitives.

The Camelot wheel maps musical keys to a numbered circle (1-12) with
inner (A = minor) and outer (B = major) rings. Adjacent positions
on the wheel are harmonically compatible.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CamelotPosition:
    """Position on the Camelot wheel."""

    number: int  # 1-12
    letter: str  # "A" (minor) or "B" (major)

    def __str__(self) -> str:
        return f"{self.number}{self.letter}"


# Map of all common key representations to Camelot positions.
# Covers: "C major", "C maj", "Cmaj", "CM", "C", standard notation,
# Camelot codes "8B", sharps/flats, enharmonic equivalents.
CAMELOT_MAP: dict[str, CamelotPosition] = {}

# Standard key -> Camelot mapping
_KEY_DEFINITIONS: list[tuple[int, str, list[str]]] = [
    # (camelot_number, letter, [key_names])
    # Minor keys (A ring)
    (1, "A", ["A-flat minor", "Ab minor", "Ab min", "Abm", "G# minor", "G#m", "G# min"]),
    (2, "A", ["E-flat minor", "Eb minor", "Eb min", "Ebm", "D# minor", "D#m", "D# min"]),
    (3, "A", ["B-flat minor", "Bb minor", "Bb min", "Bbm", "A# minor", "A#m", "A# min"]),
    (4, "A", ["F minor", "F min", "Fm"]),
    (5, "A", ["C minor", "C min", "Cm"]),
    (6, "A", ["G minor", "G min", "Gm"]),
    (7, "A", ["D minor", "D min", "Dm"]),
    (8, "A", ["A minor", "A min", "Am"]),
    (9, "A", ["E minor", "E min", "Em"]),
    (10, "A", ["B minor", "B min", "Bm"]),
    (11, "A", ["F-sharp minor", "F# minor", "F# min", "F#m", "Gb minor", "Gbm", "Gb min"]),
    (12, "A", ["D-flat minor", "Db minor", "Db min", "Dbm", "C# minor", "C#m", "C# min"]),
    # Major keys (B ring)
    # Note: Do NOT include "BM", "FM", etc. — lowercased they collide with
    # minor abbreviations ("bm" = B minor, "fm" = F minor). Use "Bmaj" instead.
    (1, "B", ["B major", "B maj", "Bmaj"]),
    (2, "B", ["F-sharp major", "F# major", "F# maj", "F#maj", "Gb major", "Gbmaj", "Gb maj"]),
    (3, "B", ["D-flat major", "Db major", "Db maj", "Dbmaj", "C# major", "C#maj", "C# maj"]),
    (4, "B", ["A-flat major", "Ab major", "Ab maj", "Abmaj", "G# major", "G#maj", "G# maj"]),
    (5, "B", ["E-flat major", "Eb major", "Eb maj", "Ebmaj", "D# major", "D#maj", "D# maj"]),
    (6, "B", ["B-flat major", "Bb major", "Bb maj", "Bbmaj", "A# major", "A#maj", "A# maj"]),
    (7, "B", ["F major", "F maj", "Fmaj"]),
    (8, "B", ["C major", "C maj", "Cmaj"]),
    (9, "B", ["G major", "G maj", "Gmaj"]),
    (10, "B", ["D major", "D maj", "Dmaj"]),
    (11, "B", ["A major", "A maj", "Amaj"]),
    (12, "B", ["E major", "E maj", "Emaj"]),
]

# Build the map
for _num, _letter, _names in _KEY_DEFINITIONS:
    pos = CamelotPosition(number=_num, letter=_letter)
    # Add Camelot code itself (e.g. "8A", "8B")
    CAMELOT_MAP[f"{_num}{_letter}"] = pos
    CAMELOT_MAP[f"{_num}{_letter.lower()}"] = pos
    for name in _names:
        CAMELOT_MAP[name.lower()] = pos

# Clean up module namespace
del _num, _letter, _names, pos


def parse_key(key_str: str | None) -> CamelotPosition | None:
    """Parse a musical key string into a Camelot wheel position.

    Handles formats: "A minor", "Am", "A min", "8A", "C maj",
    Beatport/Tidal key strings, and Camelot codes.

    Returns None for unrecognizable or empty input.
    """
    if not key_str or not key_str.strip():
        return None

    normalized = key_str.strip().lower()

    # Direct lookup
    result = CAMELOT_MAP.get(normalized)
    if result:
        return result

    # Try without extra whitespace
    compressed = " ".join(normalized.split())
    result = CAMELOT_MAP.get(compressed)
    if result:
        return result

    # Try matching just the Camelot code pattern (e.g. "8A" or "12B")
    stripped = normalized.replace(" ", "")
    if len(stripped) >= 2 and stripped[-1] in ("a", "b"):
        num_part = stripped[:-1]
        if num_part.isdigit():
            num = int(num_part)
            if 1 <= num <= 12:
                return CamelotPosition(number=num, letter=stripped[-1].upper())

    # Handle bare note names from Tidal (e.g. "Eb", "G", "CSharp", "FSharp")
    # Tidal returns keys without major/minor qualifier — default to major
    bare_key = _normalize_bare_key(key_str.strip())
    if bare_key:
        result = CAMELOT_MAP.get(bare_key.lower())
        if result:
            return result

    return None


# Mapping for Tidal's "CSharp" / "FSharp" etc. to standard notation
_TIDAL_KEY_MAP: dict[str, str] = {
    "csharp": "c#",
    "dsharp": "d#",
    "esharp": "f",
    "fsharp": "f#",
    "gsharp": "g#",
    "asharp": "a#",
    "bsharp": "c",
    "cflat": "b",
    "dflat": "db",
    "eflat": "eb",
    "fflat": "e",
    "gflat": "gb",
    "aflat": "ab",
    "bflat": "bb",
}


def _normalize_bare_key(key_str: str) -> str | None:
    """Convert a bare key name (no major/minor) to 'X major' format.

    Handles: "Eb" → "Eb major", "CSharp" → "C# major", "G" → "G major".
    Returns None if the string doesn't look like a bare key name.
    """
    lowered = key_str.lower().strip()

    # Check Tidal-style "CSharp", "FSharp" etc.
    if lowered in _TIDAL_KEY_MAP:
        return f"{_TIDAL_KEY_MAP[lowered]} major"

    # Single letter (A-G) or letter + accidental (Eb, F#, Bb, etc.)
    if len(lowered) >= 1 and lowered[0] in "abcdefg":
        rest = lowered[1:]
        if rest in ("", "b", "#"):
            # Reconstruct with proper casing
            note = key_str[0].upper() + rest
            return f"{note} major"

    return None


def compatibility_score(a: CamelotPosition | None, b: CamelotPosition | None) -> float:
    """Score harmonic compatibility between two Camelot positions.

    Returns:
        1.0 — same key (perfect match)
        0.8 — adjacent on wheel (+/-1) or parallel (A<->B at same position)
        0.5 — two positions away
        0.0 — incompatible or either key is None
    """
    if a is None or b is None:
        return 0.0

    if a == b:
        return 1.0

    # Parallel key (same number, different letter)
    if a.number == b.number and a.letter != b.letter:
        return 0.8

    # Adjacent on the wheel (same letter, +/-1 with wrap-around)
    if a.letter == b.letter:
        diff = abs(a.number - b.number)
        # Handle wrap-around: 12 -> 1 is distance 1
        circular_diff = min(diff, 12 - diff)
        if circular_diff == 1:
            return 0.8
        if circular_diff == 2:
            return 0.5

    return 0.0


def score_bpm(candidate_bpm: float | None, avg_bpm: float | None) -> float:
    """Score BPM compatibility.

    1.0 within +/-2 BPM of average, linear falloff to 0.0 at +/-20.
    Half-time (0.5x) and double-time (2.0x) matches are recognized
    as compatible but scored at 70% of normal (standard DJ technique).
    0.5 if either BPM is missing.
    """
    if candidate_bpm is None or avg_bpm is None:
        return 0.5

    diff = abs(candidate_bpm - avg_bpm)
    half_diff = abs(candidate_bpm - avg_bpm * 0.5)
    double_diff = abs(candidate_bpm - avg_bpm * 2.0)

    # Use the best (smallest) effective difference
    use_alt = False
    effective_diff = diff
    if half_diff < diff or double_diff < diff:
        best_alt = min(half_diff, double_diff)
        if best_alt < diff:
            effective_diff = best_alt
            use_alt = True

    if effective_diff <= 2.0:
        base = 1.0
    elif effective_diff >= 20.0:
        base = 0.0
    else:
        base = 1.0 - (effective_diff - 2.0) / 18.0

    # Half/double-time matches scored at 70% of normal
    if use_alt:
        return round(base * 0.7, 4)
    return base


GENRE_FAMILIES: dict[str, str] = {
    # House family
    "house": "house",
    "deep house": "house",
    "tech house": "house",
    "progressive house": "house",
    "electro house": "house",
    "bass house": "house",
    "acid house": "house",
    "funky house": "house",
    "afro house": "house",
    "minimal house": "house",
    # Techno family
    "techno": "techno",
    "minimal techno": "techno",
    "acid techno": "techno",
    "hard techno": "techno",
    "melodic techno": "techno",
    "peak time techno": "techno",
    "industrial techno": "techno",
    # Trance family
    "trance": "trance",
    "progressive trance": "trance",
    "uplifting trance": "trance",
    "psytrance": "trance",
    "vocal trance": "trance",
    # Bass family
    "drum and bass": "bass",
    "dubstep": "bass",
    "jungle": "bass",
    "breakbeat": "bass",
    "garage": "bass",
    "uk garage": "bass",
    # Hip-hop / R&B family
    "hip hop": "hip-hop",
    "hip-hop": "hip-hop",
    "rap": "hip-hop",
    "trap": "hip-hop",
    "r&b": "hip-hop",
    "rnb": "hip-hop",
    # Pop / mainstream
    "pop": "pop",
    "dance pop": "pop",
    "synth pop": "pop",
    "indie pop": "pop",
    # Rock family
    "rock": "rock",
    "alternative rock": "rock",
    "indie rock": "rock",
    "punk": "rock",
    "metal": "rock",
    # Country / folk
    "country": "country",
    "folk": "country",
    "americana": "country",
    "bluegrass": "country",
    # Electronic (broad umbrella)
    "electronic": "electronic",
    "electronica": "electronic",
    "ambient": "electronic",
    "downtempo": "electronic",
    "idm": "electronic",
}

FAMILY_AFFINITY: dict[tuple[str, str], float] = {
    ("house", "techno"): 0.4,
    ("house", "trance"): 0.3,
    ("techno", "trance"): 0.3,
    ("electronic", "house"): 0.3,
    ("electronic", "techno"): 0.3,
    ("electronic", "trance"): 0.3,
    ("bass", "electronic"): 0.3,
    ("hip-hop", "pop"): 0.3,
    ("pop", "rock"): 0.2,
}


def score_genre(candidate_genre: str | None, dominant_genres: list[str]) -> float:
    """Score genre compatibility using exact, substring, family, and affinity matching.

    1.0 = exact match, 0.5 = substring match, 0.4 = same genre family,
    0.2-0.4 = related families, 0.25 if missing, 0.0 if no relation.
    """
    if not candidate_genre:
        return 0.25

    if not dominant_genres:
        return 0.25

    candidate_lower = candidate_genre.lower()

    # 1.0 = exact match
    for dg in dominant_genres:
        if candidate_lower == dg.lower():
            return 1.0

    # 0.5 = substring match (e.g. "house" in "deep house")
    for dg in dominant_genres:
        dg_lower = dg.lower()
        if candidate_lower in dg_lower or dg_lower in candidate_lower:
            return 0.5

    # 0.4 = same genre family (e.g. "deep house" + "tech house" both → "house")
    candidate_family = GENRE_FAMILIES.get(candidate_lower)
    if candidate_family:
        for dg in dominant_genres:
            dg_family = GENRE_FAMILIES.get(dg.lower())
            if dg_family and candidate_family == dg_family:
                return 0.4

    # 0.2-0.4 = related families (e.g. "house" family + "techno" family)
    if candidate_family:
        best_affinity = 0.0
        for dg in dominant_genres:
            dg_family = GENRE_FAMILIES.get(dg.lower())
            if dg_family:
                pair = tuple(sorted([candidate_family, dg_family]))
                affinity = FAMILY_AFFINITY.get(pair, 0.0)
                if affinity > best_affinity:
                    best_affinity = affinity
        if best_affinity > 0:
            return best_affinity

    return 0.0
