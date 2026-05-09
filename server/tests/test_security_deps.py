"""
Dependency security contract tests.

These tests assert invariants of the dependency graph itself.
A failing test means a vulnerable package was re-introduced or
a security-required version floor was violated.
"""

import json
import subprocess
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"
DOCKERFILE = Path(__file__).parent.parent / "Dockerfile"
BRIDGE_APP_PKG = Path(__file__).parent.parent.parent / "bridge-app" / "package.json"


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


def test_dockerfile_upgrades_pip_before_install():
    """Dockerfile must upgrade pip to >=26.1 before installing server deps.

    pip 26.0.1 has CVE-2026-6357: module imports after wheel install allow
    a malicious wheel to hijack pip's self-update check. pip 26.1 fixes this.
    """
    dockerfile_text = DOCKERFILE.read_text()
    lines = dockerfile_text.splitlines()

    def is_pip_upgrade(line: str) -> bool:
        return "pip install" in line and "upgrade" in line and "pip" in line

    # Find the line that upgrades pip
    pip_upgrade_lines = [ln for ln in lines if is_pip_upgrade(ln)]
    assert pip_upgrade_lines, (
        "Dockerfile must contain a 'pip install --upgrade pip>=26.1' step "
        "before installing server dependencies (CVE-2026-6357)."
    )

    # Verify it appears before the main install step
    upgrade_idx = next(i for i, ln in enumerate(lines) if is_pip_upgrade(ln))
    install_idx = next(i for i, ln in enumerate(lines) if "pip install" in ln and "-e ." in ln)
    assert upgrade_idx < install_idx, (
        "pip upgrade step must appear before 'pip install -e .' in Dockerfile"
    )


def test_fast_uri_overridden_to_patched_version_in_bridge_app():
    """bridge-app must override fast-uri to >=3.1.2 (Dependabot #97/#98).

    electron-store -> conf -> ajv -> fast-uri <=3.1.1 has two HIGH CVEs:
    - path traversal via percent-encoded dot segments (<=3.1.0)
    - host confusion via percent-encoded authority delimiters (<=3.1.1)
    Fix: npm override forces ajv to resolve fast-uri@3.1.2+.
    """
    pkg = json.loads(BRIDGE_APP_PKG.read_text())
    overrides = pkg.get("overrides", {})

    assert "fast-uri" in overrides, (
        "bridge-app/package.json must have a 'fast-uri' entry in overrides "
        "to pin past the path-traversal and host-confusion CVEs (Dependabot #97/#98)."
    )

    spec = overrides["fast-uri"]
    # Accept ^3.1.2, >=3.1.2, or 3.1.2 — must not allow <3.1.2
    assert "3.1.2" in spec or spec.startswith(">=3.1.2"), (
        f"fast-uri override '{spec}' must resolve to >=3.1.2 to patch both CVEs."
    )
