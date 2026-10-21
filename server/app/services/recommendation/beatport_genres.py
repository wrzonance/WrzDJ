"""Beatport genre ID mapping for structured browse queries.

Maps genre strings (as they appear in EventProfile.dominant_genres)
to Beatport integer genre IDs required by /v4/catalog/tracks/.
"""

# Canonical Beatport genre IDs (from GET /v4/catalog/genres/)
# Keys are lowercase for case-insensitive matching.
_GENRE_NAME_TO_ID: dict[str, int] = {
    # House family
    "house": 5,
    "tech house": 11,
    "deep house": 12,
    "progressive house": 15,
    "afro house": 89,
    "bass house": 91,
    "funky house": 81,
    "jackin house": 97,
    "organic house": 93,
    "melodic house & techno": 90,
    # Techno family
    "techno": 6,
    "techno (peak time / driving)": 6,
    "techno (raw / deep / hypnotic)": 92,
    "hard techno": 2,
    "minimal / deep tech": 14,
    "minimal": 14,
    # Trance family
    "trance": 7,
    "trance (main floor)": 7,
    "trance (raw / deep / hypnotic)": 99,
    "psy-trance": 13,
    "psytrance": 13,
    # Bass family
    "drum & bass": 1,
    "drum and bass": 1,
    "dubstep": 18,
    "140 / deep dubstep / grime": 95,
    "bass / club": 85,
    "breaks / breakbeat / uk bass": 9,
    "breaks": 9,
    "breakbeat": 9,
    "uk garage / bassline": 86,
    "uk garage": 86,
    "trap / future bass": 38,
    # Other electronic
    "electronica": 3,
    "electro": 94,
    "electro (classic / detroit / modern)": 94,
    "indie dance": 37,
    "nu disco / disco": 50,
    "nu disco": 50,
    "disco": 50,
    "downtempo": 63,
    "ambient / experimental": 100,
    "ambient": 100,
    "hard dance / hardcore / neo rave": 8,
    "hardcore": 8,
    "mainstage": 96,
    # Non-electronic (Beatport has these too)
    "dance / pop": 39,
    "dance": 39,
    "pop": 107,
    "hip-hop": 105,
    "hip hop": 105,
    "r&b": 108,
    "rock": 109,
    "country": 104,
    "latin": 106,
    "african": 102,
    "amapiano": 98,
    "brazilian funk": 101,
    "caribbean": 103,
}


def resolve_genre_id(genre_name: str) -> int | None:
    """Resolve a genre string to a Beatport genre ID.

    Tries exact match (case-insensitive), then substring containment.
    Returns None if no match found.
    """
    if not genre_name:
        return None

    lower = genre_name.lower().strip()

    # Exact match
    if lower in _GENRE_NAME_TO_ID:
        return _GENRE_NAME_TO_ID[lower]

    # Prefer the most specific known genre contained in an extended profile
    # label (e.g. "Tech House (Peak Time)" should beat the broader "House").
    contained = [(known, gid) for known, gid in _GENRE_NAME_TO_ID.items() if known in lower]
    if contained:
        return max(contained, key=lambda match: len(match[0]))[1]

    # For short partial labels, choose the closest known name rather than the
    # first broader entry in the mapping.
    partial = [(known, gid) for known, gid in _GENRE_NAME_TO_ID.items() if lower in known]
    if partial:
        return min(partial, key=lambda match: len(match[0]))[1]

    return None
