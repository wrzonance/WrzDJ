"""Recommendation query test builder."""

from app.services.recommendation.llm_hooks import LLMSuggestionQuery


def _make_query(
    search_query="test",
    target_bpm=None,
    target_key=None,
    target_genre=None,
):
    return LLMSuggestionQuery(
        search_query=search_query,
        target_bpm=target_bpm,
        target_key=target_key,
        target_genre=target_genre,
        reasoning="test",
    )
