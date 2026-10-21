from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_current_admin, get_db
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.models.search_cache import SearchCache
from app.models.user import User
from app.schemas.common import CacheClearResponse
from app.schemas.search import SearchResult
from app.services.intent_parser import parse_intent
from app.services.system_settings import get_system_settings

router = APIRouter()


@router.get("", response_model=list[SearchResult])
@limiter.limit(lambda: f"{get_settings().search_rate_limit_per_minute}/minute")
def search(
    request: Request,
    q: str = Query(..., min_length=2, max_length=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[SearchResult]:
    """DJ search endpoint. Tidal primary, Spotify fallback."""
    from app.services.providers.spotify import search_songs
    from app.services.providers.tidal import search_tidal_tracks
    from app.services.search_merge import build_search_results

    sys_settings = get_system_settings(db)
    intent = parse_intent(q)

    # Tidal primary: search if user has Tidal linked
    tidal_results = []
    if current_user.tidal_access_token:
        tidal_results = search_tidal_tracks(db, current_user, q, limit=20)

    # Spotify fallback: only if Tidal returned nothing AND Spotify is enabled
    spotify_results = []
    if not tidal_results and sys_settings.spotify_enabled:
        spotify_results = search_songs(db, q)

    if not current_user.tidal_access_token and not sys_settings.spotify_enabled:
        raise HTTPException(status_code=503, detail="Song search is currently unavailable")

    return build_search_results(
        tidal_results=tidal_results or None,
        spotify_results=spotify_results or None,
        intent=intent,
    )


@router.delete("/cache", response_model=CacheClearResponse)
def clear_search_cache(
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> CacheClearResponse:
    """Clear all cached search results (admin only)."""
    count = db.query(SearchCache).delete()
    db.commit()
    return CacheClearResponse(message=f"Cleared {count} cached search results")
