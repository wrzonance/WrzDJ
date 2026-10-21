"""Shared Beatport API values used by provider workflow modules."""

import re

BEATPORT_API_BASE = "https://api.beatport.com/v4"
BEATPORT_TRACK_URL = "https://www.beatport.com/track/{slug}/{track_id}"
HTTP_TIMEOUT = 15.0
DEFAULT_TOKEN_EXPIRY = 600
_BEATPORT_ID_RE = re.compile(r"^[0-9]{1,20}$")


def is_valid_beatport_id(value: str) -> bool:
    """Beatport catalog and playlist IDs are decimal integers.

    Anything else must never be interpolated into an API path: a value such as
    ``../search/?q=`` would redirect the caller's bearer token to a different
    Beatport endpoint (CodeQL py/partial-ssrf).
    """
    return isinstance(value, str) and _BEATPORT_ID_RE.fullmatch(value) is not None


def parse_duration(length_str: str | None) -> int | None:
    """Parse Beatport duration string (e.g., '5:30' or '05:30') to seconds."""
    if not length_str:
        return None
    try:
        parts = length_str.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except (ValueError, IndexError):
        pass  # unparseable duration string: report unknown length
    return None
