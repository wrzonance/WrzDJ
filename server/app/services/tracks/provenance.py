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
    "llm": 10,
}

KNOWN_SOURCES: frozenset[str] = frozenset(SOURCE_PRECEDENCE)


class FieldProvenance(BaseModel):
    source: str
    fetched_at: datetime


def precedence(source: str) -> int:
    return SOURCE_PRECEDENCE.get(source, 0)


def should_overwrite(existing: dict | None, new_source: str) -> bool:
    """True if a value sourced from new_source may replace the existing field."""
    if existing is None:
        return True
    return precedence(new_source) >= precedence(existing.get("source", ""))
