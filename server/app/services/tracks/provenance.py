"""Per-field provenance + source-precedence for the master tracks store (#540).

The stored JSON shape is {field: {"source": str, "fetched_at": ISO8601 str}}.
Precedence guards the cascade: a lower-trust source never downgrades a higher
one (measured energy must survive a later LLM re-inference).
"""

from datetime import datetime

from pydantic import BaseModel

SOURCE_PRECEDENCE: dict[str, int] = {
    "manual": 100,
    "lexicon": 90,
    "soundcharts": 50,
    "beatport": 50,
    "tidal": 50,
    "musicbrainz": 50,
    "community": 40,
    # Pre-store data backfilled from existing Request columns (#541): carries no
    # original-source record, so it sits lowest above the unknown floor — any real
    # later enrichment cleanly overrides it, and it never downgrades a real source.
    "legacy": 30,
    "llm": 10,
}

KNOWN_SOURCES: frozenset[str] = frozenset(SOURCE_PRECEDENCE)


class FieldProvenance(BaseModel):
    source: str
    fetched_at: datetime


def precedence(source: str) -> int:
    return SOURCE_PRECEDENCE.get(source, 0)


# A cached track row may only short-circuit live enrichment when its fields come
# from a real measured/authoritative provider (the 50+ tier: soundcharts/beatport/
# tidal/musicbrainz and above). community(40)/legacy(30)/llm(10)/unknown(0) are
# low-trust: a row sourced only from them must fall through so real providers can
# upgrade it, rather than being served as a sticky cache hit (#541).
CACHE_TRUST_FLOOR = 50


def is_cache_authoritative(source: str) -> bool:
    """True if a field from this source may serve as an authoritative cache hit.

    Unknown/missing sources (precedence 0) are NOT authoritative, so an
    unprovenanced complete row cannot short-circuit provider upgrades."""
    return precedence(source) >= CACHE_TRUST_FLOOR


def should_overwrite(existing: dict | None, new_source: str) -> bool:
    """True if a value sourced from new_source may replace the existing field."""
    if existing is None:
        return True
    return precedence(new_source) >= precedence(existing.get("source", ""))
