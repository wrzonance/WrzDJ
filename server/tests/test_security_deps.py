"""
Dependency security contract tests.

These tests assert invariants of the dependency graph itself.
A failing test means a vulnerable package was re-introduced.

Version-floor enforcement (pip CVE-2026-6357, fast-uri Dependabot #97/#98)
is intentionally left to pip-audit and npm audit in CI — duplicating that
logic here with custom version parsing is fragile and adds no real coverage.
"""

import subprocess
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"


def test_ecdsa_not_a_direct_dependency():
    """ecdsa has an unpatched Minerva timing-attack CVE (Dependabot #96).

    It was pinned as a direct dep to floor a transitive dep of python-jose,
    but python-jose is no longer required by anything in the server.
    This test fails if ecdsa is re-added to pyproject.toml.
    """
    with open(PYPROJECT, "rb") as f:
        data = tomllib.load(f)

    direct_deps = data["project"]["dependencies"]
    ecdsa_deps = [d for d in direct_deps if d.lower().startswith("ecdsa")]
    assert ecdsa_deps == [], (
        f"ecdsa must not be a direct dependency (unpatched CVE, orphaned pin). Found: {ecdsa_deps}"
    )


def test_no_jose_or_ecdsa_imports_in_server_code():
    """Server application code must not import from ecdsa or jose.

    Guards against a future developer reintroducing a dependency on
    python-jose (which pulls in the vulnerable ecdsa package).
    """
    result = subprocess.run(
        [
            "grep",
            "-r",
            "--include=*.py",
            "-l",
            r"from ecdsa\|import ecdsa\|from jose\|import jose\|from python_jose\|python-jose",
            "app/",
        ],
        capture_output=True,
        text=True,
        cwd=PYPROJECT.parent,
    )
    assert result.stdout.strip() == "", (
        f"Server code imports from ecdsa/jose (vulnerable). Files: {result.stdout.strip()}"
    )
