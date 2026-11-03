from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

settings = get_settings()

# Pool sized for a busy night: dashboard polls, kiosks and guest phones all borrow briefly.
# A short checkout timeout frees worker threads quickly when the pool is momentarily dry,
# instead of parking them for 30 s (which starved the threadpool and hung /health).
# 10 + 20 stays far below Postgres's default 100 connections.
POOL_SIZE = 10
POOL_MAX_OVERFLOW = 20
POOL_TIMEOUT_SECONDS = 10

_pool_args = (
    {}  # SQLite (tests, local tools) has its own pool classes that reject these arguments.
    if settings.database_url_sync.startswith("sqlite")
    else {
        "pool_size": POOL_SIZE,
        "max_overflow": POOL_MAX_OVERFLOW,
        "pool_timeout": POOL_TIMEOUT_SECONDS,
    }
)

engine = create_engine(settings.database_url_sync, pool_pre_ping=True, **_pool_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
