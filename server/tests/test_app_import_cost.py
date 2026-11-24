"""Importing the app must not load vendor LLM SDKs (#1008).

``anthropic`` alone took ~2.5 s of a ~9.5 s ``import app.main``, paid by every process
that imports the app: each xdist worker, the OpenAPI export, alembic, and server start.
Adapters load their SDK on first use instead. Runs in a fresh interpreter, because this
test process has long since imported everything.
"""

import subprocess
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
LAZY_SDKS = ("anthropic",)


def test_importing_the_app_does_not_load_vendor_llm_sdks():
    probe = (
        "import sys, app.main; "
        f"print(','.join(m for m in {LAZY_SDKS!r} if m in sys.modules) or 'none')"
    )
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
        [sys.executable, "-c", probe],
        cwd=SERVER_DIR,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip().splitlines()[-1] == "none"
