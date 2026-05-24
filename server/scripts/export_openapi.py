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
from pathlib import Path
from typing import Any

from app.main import app


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


def export() -> Path:
    output = Path(__file__).resolve().parent.parent / "openapi.json"
    # Force fresh generation — FastAPI caches the schema on `app.openapi_schema`,
    # which can hide newly-added routes when this script is invoked from a
    # long-running process.
    app.openapi_schema = None
    spec = app.openapi()
    _promote_response_fields_to_required(spec)
    output.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    return output


if __name__ == "__main__":
    path = export()
    print(f"Wrote OpenAPI schema to {path}")
