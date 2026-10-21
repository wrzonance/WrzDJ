"""Shared response mapping for request API routes."""

from app.models.request import Request
from app.schemas.request import RequestOut


def request_to_out(request: Request) -> RequestOut:
    """Convert a Request model to its public response schema."""
    return RequestOut(
        id=request.id,
        event_id=request.event_id,
        song_title=request.song_title,
        artist=request.artist,
        source=request.source,
        source_url=request.source_url,
        artwork_url=request.artwork_url,
        note=request.note,
        nickname=request.nickname,
        status=request.status,
        created_at=request.created_at,
        updated_at=request.updated_at,
        accepted_at=request.accepted_at,
        raw_search_query=request.raw_search_query,
        sync_results_json=request.sync_results_json,
        vote_count=request.vote_count,
        genre=request.genre,
        bpm=request.bpm,
        musical_key=request.musical_key,
    )
