"""Normalization and validation for provider-neutral track identifiers."""

import re

_ISRC_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$")


def normalize_isrc(isrc: str | None) -> str | None:
    """Normalize an ISRC to uppercase without separators, or return None."""
    if not isrc:
        return None
    cleaned = isrc.strip().upper().replace("-", "").replace(" ", "")
    return cleaned or None


def valid_isrc(isrc: str | None) -> str | None:
    """Return a normalized ISRC only when it matches the ISO 3901 shape."""
    normalized = normalize_isrc(isrc)
    if normalized and _ISRC_RE.match(normalized):
        return normalized
    return None
