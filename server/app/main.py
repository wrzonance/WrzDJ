import asyncio
import contextlib
import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi import Request as FastAPIRequest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from app.api import api_router
from app.core.config import get_settings
from app.core.logging_config import configure_logging
from app.core.rate_limit import limiter, rate_limit_exceeded_handler
from app.core.security_headers import SecurityHeadersMiddleware

# Ensure WebP MIME type is registered (missing on some minimal Docker images)
mimetypes.add_type("image/webp", ".webp")

settings = get_settings()

configure_logging()
logger = logging.getLogger(__name__)

# Explicit CORS methods for non-wildcard origins — must include every HTTP method used by the API
CORS_ALLOW_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]

TIDAL_COLLECTION_POLL_INTERVAL_SECONDS = 300  # 5 minutes
LLM_CALL_LOG_CLEANUP_INTERVAL_SECONDS = 86400  # 24 hours


def _run_llm_call_log_cleanup() -> None:
    """Synchronous daily cleanup of expired llm_call_log rows.

    Reads ``llm_call_log_retention_days`` from system settings each run, so an
    admin change to the retention window takes effect on the next pass (within
    24h) without a restart. Executed in a thread to avoid blocking the loop.
    """
    from app.db.session import SessionLocal
    from app.services.llm.connector_storage import purge_call_log_older_than
    from app.services.system_settings import get_system_settings

    db = SessionLocal()
    try:
        retention_days = get_system_settings(db).llm_call_log_retention_days
        deleted = purge_call_log_older_than(db, retention_days=retention_days)
        db.commit()
        if deleted:
            logger.info(
                "llm_call_log cleanup deleted %s rows older than %s days",
                deleted,
                retention_days,
            )
    finally:
        db.close()


async def _llm_call_log_cleanup_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(_run_llm_call_log_cleanup)
        except Exception:
            logger.exception("llm_call_log cleanup loop error")
        await asyncio.sleep(LLM_CALL_LOG_CLEANUP_INTERVAL_SECONDS)


def _run_tidal_collection_poll() -> None:
    """Synchronous poll, executed in a thread to avoid blocking the event loop."""
    from app.db.session import SessionLocal
    from app.models.event import Event
    from app.services.tidal import poll_tidal_collection_removals

    db = SessionLocal()
    try:
        events = (
            db.query(Event)
            .filter(
                Event.tidal_sync_enabled == True,  # noqa: E712
                Event.tidal_collection_bidirectional == True,  # noqa: E712
                Event.tidal_collection_playlist_id.isnot(None),
            )
            .all()
        )
        for event in events:
            if event.phase == "collection":
                try:
                    poll_tidal_collection_removals(db, event)
                except Exception:
                    logger.exception("Tidal collection poll failed for event %s", event.code)
    finally:
        db.close()


async def _tidal_collection_poll_loop() -> None:
    while True:
        await asyncio.sleep(TIDAL_COLLECTION_POLL_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(_run_tidal_collection_poll)
        except Exception:
            logger.exception("Tidal collection poll loop error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    # Import lazily so test runs that mock out the loop module don't trigger
    # adapter imports at startup-time.
    from app.services.llm.health_monitor import health_monitor_loop

    tasks = [
        asyncio.create_task(_tidal_collection_poll_loop()),
        asyncio.create_task(_llm_call_log_cleanup_loop()),
        asyncio.create_task(health_monitor_loop()),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title="WrzDJ API",
    description="Song request system for DJs",
    version="0.1.0",
    lifespan=lifespan,
    # Disable API docs in production
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def global_exception_handler(request: FastAPIRequest, exc: Exception) -> JSONResponse:
    """Catch unhandled exceptions and return a generic 500 response."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    content = {"detail": "Internal server error"}
    if not settings.is_production:
        content["debug"] = str(exc)
    return JSONResponse(status_code=500, content=content)


# Security headers (added first, runs last in middleware chain)
app.add_middleware(SecurityHeadersMiddleware)

# CORS
if settings.cors_origins.strip() == "*":
    # Allow all origins for local development (no credentials needed for Bearer token auth)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    origins = [origin.strip() for origin in settings.cors_origins.split(",")]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=CORS_ALLOW_METHODS,
        allow_headers=["Authorization", "Content-Type", "X-Kiosk-Session"],
    )

# Include API router
app.include_router(api_router, prefix="/api")

# Serve uploaded files (banners, etc.)
uploads_dir = Path(settings.resolved_uploads_dir)
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")


@app.get("/health")
def health_check():
    return {"status": "ok"}
