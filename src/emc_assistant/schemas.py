"""Hard JSON-schema validation for pipeline artefacts.

Every artefact written to ``generated/`` or ``results/`` must validate
against the corresponding schema in ``schemas/``. If ``jsonschema`` is
not installed, validators degrade to no-ops (matches the minimal MVP
environment).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = REPO_ROOT / "schemas"


class SchemaValidationError(ValueError):
    """Raised when an artefact violates its JSON-schema contract."""

    def __init__(self, schema_name: str, errors: list[str]) -> None:
        self.schema_name = schema_name
        self.errors = errors
        joined = "\n  - ".join(errors) if errors else "(no details)"
        super().__init__(f"Validation of {schema_name} failed:\n  - {joined}")


@lru_cache(maxsize=None)
def _load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def _build_registry() -> object | None:
    """Build a ``referencing.Registry`` populated with every local schema.

    Returns ``None`` when ``referencing`` is not installed. The registry
    lets schemas like ``agent_finding.schema.json`` reference
    ``recommendation.schema.json`` by file name without hitting the
    network on validation.
    """
    if jsonschema is None:
        return None
    try:
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT202012
    except ImportError:  # pragma: no cover
        return None
    resources: list[tuple[str, object]] = []
    for path in SCHEMAS_DIR.glob("*.schema.json"):
        with path.open("r", encoding="utf-8") as fh:
            schema_dict = json.load(fh)
        resource = Resource(contents=schema_dict, specification=DRAFT202012)
        resources.append((path.name, resource))
        schema_id = schema_dict.get("$id")
        if schema_id:
            resources.append((schema_id, resource))
    return Registry().with_resources(resources)


def validate_against(schema_name: str, data: dict) -> list[str]:
    """Return a list of validation errors. Empty == valid. No-op without ``jsonschema``."""
    if jsonschema is None:
        return []
    schema = _load_schema(schema_name)
    registry = _build_registry()
    if registry is not None:
        validator = jsonschema.Draft202012Validator(schema, registry=registry)
    else:  # pragma: no cover
        validator = jsonschema.Draft202012Validator(schema)
    errors: list[str] = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        path = ".".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"{path}: {err.message}")
    return errors


def require_valid(schema_name: str, data: dict) -> None:
    """Raise ``SchemaValidationError`` when the artefact is invalid."""
    errors = validate_against(schema_name, data)
    if errors:
        raise SchemaValidationError(schema_name, errors)


def require_all_valid(schema_name: str, items: Iterable[dict]) -> None:
    """Validate every element in an iterable."""
    aggregated: list[str] = []
    for idx, item in enumerate(items):
        errors = validate_against(schema_name, item)
        for e in errors:
            aggregated.append(f"[{idx}] {e}")
    if aggregated:
        raise SchemaValidationError(schema_name, aggregated)
