"""Tests for the ``LLM_PLUGIN_DIR`` filesystem plug-in loader.

The loader is an optional surface — production deploys typically leave the
env var unset and ship trusted adapters as ordinary Python modules. These
tests pin its documented behaviour:

- Importable ``.py`` files are loaded.
- Files starting with ``_`` and any non-``.py`` files are skipped.
- A single broken plug-in logs an error and does **not** stop loading the
  rest of the directory.
- The loader does not mutate ``sys.path`` (no namespace leakage).
"""

from __future__ import annotations

import logging
import sys

import pytest

from app.services.llm import plugin_loader


@pytest.fixture
def isolated_sys_path():
    """Snapshot and restore ``sys.path`` around each loader test.

    The loader is explicitly documented to *not* add the plug-in directory to
    ``sys.path``. Snapshotting here lets us assert that no entry leaks out.
    """
    before = list(sys.path)
    yield
    sys.path[:] = before


@pytest.fixture
def cleanup_test_modules():
    """Drop any ``llm_plugins.*`` modules between tests so re-imports re-execute."""
    yield
    for name in list(sys.modules):
        if name.startswith("llm_plugins."):
            sys.modules.pop(name, None)


def _write_plugin(dir_path, name: str, body: str) -> None:
    (dir_path / name).write_text(body)


def test_no_env_var_loads_nothing(monkeypatch):
    monkeypatch.delenv(plugin_loader.ENV_VAR, raising=False)
    assert plugin_loader.load_plugins_from_env() == []


def test_nonexistent_directory_is_skipped_with_warning(monkeypatch, tmp_path, caplog):
    missing = tmp_path / "does-not-exist"
    monkeypatch.setenv(plugin_loader.ENV_VAR, str(missing))
    with caplog.at_level(logging.WARNING):
        assert plugin_loader.load_plugins_from_env() == []
    assert any("does not exist" in r.message for r in caplog.records)


def test_loads_py_files_skipping_underscore_and_non_py(
    monkeypatch, tmp_path, isolated_sys_path, cleanup_test_modules
):
    # A loadable plug-in — registers nothing, just imports cleanly. We use a
    # noop body to keep the assertion focused on file selection rather than
    # registry side-effects (the contract test in test_llm_adapter_contract.py
    # already covers the end-to-end registration path via the docs skeleton).
    _write_plugin(tmp_path, "good.py", "X = 1\n")
    # Anything starting with ``_`` is skipped (e.g. shared helpers).
    _write_plugin(tmp_path, "_helper.py", "raise RuntimeError('should not load')\n")
    # Non-``.py`` files are skipped.
    _write_plugin(tmp_path, "README.md", "not python\n")
    # Subdirectories are skipped (no recursion).
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "nested.py").write_text("X = 2\n")

    monkeypatch.setenv(plugin_loader.ENV_VAR, str(tmp_path))
    loaded = plugin_loader.load_plugins_from_env()
    assert loaded == ["llm_plugins.good"]
    # The loader must not contaminate sys.path with the plug-in directory.
    assert str(tmp_path) not in sys.path


def test_one_broken_plugin_does_not_block_others(
    monkeypatch, tmp_path, isolated_sys_path, cleanup_test_modules, caplog
):
    # Sorted load order: 'a' then 'z'. 'a' is broken; 'z' must still load.
    _write_plugin(tmp_path, "a_broken.py", "raise ValueError('boom at import')\n")
    _write_plugin(tmp_path, "z_good.py", "X = 1\n")

    monkeypatch.setenv(plugin_loader.ENV_VAR, str(tmp_path))
    with caplog.at_level(logging.ERROR):
        loaded = plugin_loader.load_plugins_from_env()

    assert loaded == ["llm_plugins.z_good"]
    # The error log should include the offending file name AND the stack
    # trace; operators rely on this to diagnose third-party imports.
    error_messages = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("a_broken.py" in m for m in error_messages)
    assert any("ValueError" in m and "boom at import" in m for m in error_messages)


def test_failed_plugin_does_not_leak_into_sys_modules(
    monkeypatch, tmp_path, isolated_sys_path, cleanup_test_modules
):
    _write_plugin(tmp_path, "broken.py", "raise RuntimeError('nope')\n")
    monkeypatch.setenv(plugin_loader.ENV_VAR, str(tmp_path))
    plugin_loader.load_plugins_from_env()
    assert "llm_plugins.broken" not in sys.modules


def test_load_from_dir_accepts_explicit_path(tmp_path, isolated_sys_path, cleanup_test_modules):
    _write_plugin(tmp_path, "direct.py", "X = 1\n")
    loaded = plugin_loader.load_plugins_from_dir(tmp_path)
    assert loaded == ["llm_plugins.direct"]
