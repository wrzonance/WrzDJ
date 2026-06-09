from fastapi import APIRouter

from app.api import (
    admin,
    admin_llm,
    auth,
    beatport,
    bridge,
    collect,
    events,
    guest,
    kiosk,
    llm,
    public,
    requests,
    search,
    setbuilder,
    setbuilder_share,
    sse,
    tidal,
    verify,
    votes,
)

api_router = APIRouter()


@api_router.get("/health", tags=["health"])
def api_health_check():
    """Health check endpoint for monitoring and load balancers."""
    return {"status": "ok", "service": "api"}


api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(events.router, prefix="/events", tags=["events"])
api_router.include_router(requests.router, prefix="/requests", tags=["requests"])
api_router.include_router(votes.router, prefix="/requests", tags=["votes"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(setbuilder.router, prefix="/setbuilder", tags=["setbuilder"])
api_router.include_router(setbuilder_share.router, prefix="/setbuilder", tags=["setbuilder"])
api_router.include_router(
    setbuilder_share.public_router, prefix="/public/setbuilder", tags=["setbuilder-public"]
)
api_router.include_router(public.router, prefix="/public", tags=["public"])
api_router.include_router(guest.router, prefix="/public", tags=["guest"])
api_router.include_router(verify.router, prefix="/public/guest", tags=["verify"])
api_router.include_router(collect.router, prefix="/public/collect", tags=["collect"])
api_router.include_router(sse.router, prefix="/public", tags=["sse"])
api_router.include_router(bridge.router, tags=["bridge"])
api_router.include_router(tidal.router, prefix="/tidal", tags=["tidal"])
api_router.include_router(beatport.router, prefix="/beatport", tags=["beatport"])
api_router.include_router(kiosk.public_router, prefix="/public/kiosk", tags=["kiosk"])
api_router.include_router(kiosk.auth_router, prefix="/kiosk", tags=["kiosk"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(llm.router, prefix="/llm", tags=["llm"])
api_router.include_router(admin_llm.router, prefix="/admin/llm", tags=["admin", "llm"])
