"""Test-package bootstrap.

pytest imports this before ``tests/conftest.py``, i.e. before any ``app``
module is imported and before ``get_settings()`` is first cached, so the
environment defaults below reach pydantic-settings ahead of the repo ``.env``.
"""

import os

# The whole session shares ONE in-memory SQLite connection (StaticPool with
# check_same_thread=False in conftest). sqlite3 connections are not safe for
# concurrent use, so the pool-import enrichment BackgroundTask must not fan out
# across worker threads under test: with the production default of 6 workers,
# interleaved cursor reads surface as ``IndexError`` inside SQLAlchemy's row
# processor (#662). One worker still exercises the executor code path.
os.environ.setdefault("POOL_ENRICH_CONCURRENCY", "1")

# A developer ``.env`` may switch the dev auth bypass on; pydantic-settings would
# read that into the test process and open every auth gate. Env vars beat
# ``.env``, and tests that need the bypass construct ``Settings`` explicitly.
os.environ.setdefault("DEV_AUTH_BYPASS", "0")

# The fakes in tests/fakes/providers.py describe Beatport's default auth host. A
# developer ``.env`` carrying the older BEATPORT_AUTH_BASE_URL would send the token
# revoke to a host the fakes do not know, and the outbound-HTTP guard fails the test.
os.environ.setdefault("BEATPORT_AUTH_BASE_URL", "https://account.beatport.com")
