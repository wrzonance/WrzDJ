"""Optional filesystem loader for third-party LLM adapter plug-ins.

When the ``LLM_PLUGIN_DIR`` environment variable is set to a directory path,
:func:`load_plugins_from_env` imports every ``.py`` file (non-recursive,
excluding files whose names start with ``_``) from that directory at startup.

Each imported plug-in is responsible for calling
:func:`app.services.llm.registry.register_adapter` at module load time — same
contract the built-in adapters use. The loader simply triggers the import; it
performs no monkey-patching, manifest parsing, or sandbox.

Security posture
----------------
Loading a plug-in is equivalent to giving the loaded code the full privileges
of the backend process — same as installing a Python package. There is no
sandbox. Operators must therefore:

- Treat ``LLM_PLUGIN_DIR`` as a privileged path. Only the same user that owns
  ``server/`` and its venv should have write access to it.
- Audit each plug-in's source the same way they would audit a third-party
  ``pip install``. The skeleton at ``docs/examples/echo_adapter.py`` is
  reviewed; everything else must be reviewed by whoever sets up the
  environment.
- Never set ``LLM_PLUGIN_DIR`` to a world-writable or shared-tenancy path.

In production we recommend leaving ``LLM_PLUGIN_DIR`` unset and packaging
trusted plug-ins as ordinary Python modules imported from a controlled
location. The env-var loader exists to make local experimentation and forks
ergonomic.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)

ENV_VAR = "LLM_PLUGIN_DIR"


def load_plugins_from_env() -> list[str]:
    """Load adapters from the directory named by ``LLM_PLUGIN_DIR``.

    Returns the list of module names that were successfully imported (their
    side-effectful ``register_adapter`` calls will have run by then).

    The loader is intentionally permissive: a single broken plug-in must not
    prevent the rest of the directory — or the backend process itself — from
    starting. Each import error is logged with a full stack trace and the
    plug-in name, then skipped.
    """
    dir_path = os.environ.get(ENV_VAR)
    if not dir_path:
        return []
    return load_plugins_from_dir(dir_path)


def load_plugins_from_dir(dir_path: str | os.PathLike[str]) -> list[str]:
    """Same as :func:`load_plugins_from_env` but with an explicit path."""
    root = Path(dir_path)
    if not root.is_dir():
        logger.warning(
            "%s=%s does not exist or is not a directory; skipping plug-in load",
            ENV_VAR,
            dir_path,
        )
        return []

    loaded: list[str] = []
    # Sort for stable load order — useful when one plug-in depends on another
    # being registered first (the registry rejects double-registration so the
    # *first* import of any given connector_type wins).
    for entry in sorted(root.iterdir()):
        if not _is_loadable(entry):
            continue
        # Synthesise a stable, namespaced module name to avoid colliding with
        # any installed package. We deliberately do NOT add the plug-in dir to
        # ``sys.path`` — that would also expose every other file in the dir as
        # an importable module from elsewhere in the codebase.
        module_name = f"llm_plugins.{entry.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, entry)
            if spec is None or spec.loader is None:
                logger.warning("Could not build import spec for plug-in %s", entry)
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception:
            # ``traceback.format_exc()`` is logged so operators can debug
            # plug-in import errors without crashing the backend. We pop the
            # half-imported module out of ``sys.modules`` so a later retry
            # (e.g. uvicorn --reload) re-runs the spec from scratch.
            sys.modules.pop(module_name, None)
            logger.error(
                "Failed to load LLM plug-in %s (module=%s):\n%s",
                entry.name,
                module_name,
                traceback.format_exc(),
            )
            continue
        logger.info("Loaded LLM plug-in %s (module=%s)", entry.name, module_name)
        loaded.append(module_name)
    return loaded


def _is_loadable(entry: Path) -> bool:
    """Filter the directory listing to plain ``*.py`` source files."""
    if not entry.is_file():
        return False
    if entry.suffix != ".py":
        return False
    if entry.name.startswith("_"):
        # Skip ``__init__.py`` and any conventional "private" leading-underscore
        # helpers — they are usually shared utilities, not plug-ins.
        return False
    return True
