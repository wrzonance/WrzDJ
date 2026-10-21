"""Export the FastAPI OpenAPI schema to a JSON file.

Used by the dashboard's type-generation pipeline so TypeScript types can be
generated from the backend contract without needing a live server.

Run from the server/ directory:
    .venv/bin/python scripts/export_openapi.py

Writes to server/openapi.json (relative to the repo root).

Post-processing: response-body schemas are rewritten so every property appears
in the `required` list. FastAPI always serializes every Pydantic field in a
response (Python-side defaults affect construction, not serialization), so
consumers should see fields as always-present — with `T | null` where the
type is nullable. Without this pass, openapi-typescript emits the looser
`T | null | undefined` for every field that has a Pydantic default, which
forces ~30+ call-site narrowings in the dashboard for no runtime benefit.

Request-body schemas (EventCreate, EventUpdate, etc.) keep their original
`required` list since omitting an optional field there is meaningful.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

SERVER_ROOT = Path(__file__).resolve().parent.parent
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


def _collect_refs(node: Any) -> set[str]:
    """Walk a JSON schema node and return all $ref'd component names."""
    refs: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if (
                key == "$ref"
                and isinstance(value, str)
                and value.startswith("#/components/schemas/")
            ):
                refs.add(value.rsplit("/", 1)[-1])
            else:
                refs.update(_collect_refs(value))
    elif isinstance(node, list):
        for item in node:
            refs.update(_collect_refs(item))
    return refs


def _promote_response_fields_to_required(spec: dict[str, Any]) -> None:
    """Mark every property of every response-referenced schema as `required`."""
    response_refs: set[str] = set()
    for path_data in spec.get("paths", {}).values():
        if not isinstance(path_data, dict):
            continue
        for op in path_data.values():
            if not isinstance(op, dict):
                continue
            for response in op.get("responses", {}).values():
                if not isinstance(response, dict):
                    continue
                for media in response.get("content", {}).values():
                    schema = media.get("schema", {}) if isinstance(media, dict) else {}
                    response_refs.update(_collect_refs(schema))

    schemas = spec.get("components", {}).get("schemas", {})
    visited: set[str] = set()
    to_visit = list(response_refs)
    while to_visit:
        name = to_visit.pop()
        if name in visited or name not in schemas:
            continue
        visited.add(name)
        schema = schemas[name]
        if not isinstance(schema, dict):
            continue
        # Follow nested refs (e.g. KioskDisplayResponse → PublicRequestInfo).
        to_visit.extend(_collect_refs(schema))
        properties = schema.get("properties")
        if isinstance(properties, dict) and properties:
            schema["required"] = sorted(properties.keys())


def _write_atomically(path: Path, contents: str) -> None:
    """Replace an artifact only after its complete temporary file is written."""
    temporary_path: Path | None = None
    descriptor: int | None = None
    try:
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
            descriptor = None
            temporary_file.write(contents)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def export() -> Path:
    from app.main import app

    output = SERVER_ROOT / "openapi.json"
    # Force fresh generation — FastAPI caches the schema on `app.openapi_schema`,
    # which can hide newly-added routes when this script is invoked from a
    # long-running process.
    app.openapi_schema = None
    spec = app.openapi()
    _promote_response_fields_to_required(spec)
    _write_atomically(output, json.dumps(spec, indent=2, sort_keys=True) + "\n")
    return output


if __name__ == "__main__":
    path = export()
    print(f"Wrote OpenAPI schema to {path}")
