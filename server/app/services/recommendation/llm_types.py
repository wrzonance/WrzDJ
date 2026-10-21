"""Shared data types for LLM-powered recommendation queries."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LLMSuggestionQuery:
    """A search query suggested by an LLM."""

    search_query: str  # e.g., "deadmau5 progressive house"
    target_bpm: float | None = None
    target_key: str | None = None
    target_genre: str | None = None
    reasoning: str = ""  # LLM's explanation


@dataclass(frozen=True)
class LLMSuggestionResult:
    """Result from LLM suggestion generation."""

    queries: list[LLMSuggestionQuery]
    raw_response: str  # Full LLM response for debugging
    model: str | None = None  # Provider model that actually produced the response
