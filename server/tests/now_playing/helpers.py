"""Time helpers shared by now-playing service tests."""

from datetime import UTC, datetime

__all__ = ["UTC"]


def utcnow() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(UTC)
