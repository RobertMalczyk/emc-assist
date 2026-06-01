"""`.emcproj` project model and ``project.yaml`` validation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_DIR = REPO_ROOT / "schemas"
PROJECT_SCHEMA_PATH = SCHEMAS_DIR / "project_config.schema.json"


@dataclass
class ProjectLayout:
    """`.emcproj` directory layout.

    A project is a directory. ``project.yaml`` describes its config,
    subdirectories separate user inputs from generated artefacts.
    """

    root: Path
    input_dir: Path
    generated_dir: Path
    results_dir: Path
    reports_dir: Path
    decisions_dir: Path

    @classmethod
    def for_root(cls, root: Path) -> "ProjectLayout":
        root = Path(root)
        return cls(
            root=root,
            input_dir=root / "input",
            generated_dir=root / "generated",
            results_dir=root / "results",
            reports_dir=root / "reports",
            decisions_dir=root / "decisions",
        )

    def ensure_dirs(self) -> None:
        for d in (
            self.input_dir, self.generated_dir, self.results_dir,
            self.reports_dir, self.decisions_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


@dataclass
class ProjectConfig:
    """Project configuration loaded from ``project.yaml``."""

    project_id: str
    name: str
    version: str
    created_at: str
    analysis_scope: str
    inputs: dict[str, Any] = field(default_factory=dict)
    privacy: dict[str, Any] = field(default_factory=dict)
    ltspice: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectConfig":
        return cls(
            project_id=data["project_id"],
            name=data["name"],
            version=data["version"],
            created_at=data["created_at"],
            analysis_scope=data["analysis_scope"],
            inputs=dict(data.get("inputs", {})),
            privacy=dict(data.get("privacy", {})),
            ltspice=dict(data.get("ltspice", {})),
            raw=dict(data),
        )

    def to_dict(self) -> dict[str, Any]:
        return dict(self.raw) if self.raw else {
            "project_id": self.project_id,
            "name": self.name,
            "version": self.version,
            "created_at": self.created_at,
            "analysis_scope": self.analysis_scope,
            "inputs": self.inputs,
            "privacy": self.privacy,
            "ltspice": self.ltspice,
        }


def _load_schema() -> dict[str, Any]:
    with PROJECT_SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_project_config(data: dict[str, Any]) -> list[str]:
    """Return a list of validation errors; empty means the config is valid."""
    errors: list[str] = []
    schema = _load_schema()

    if jsonschema is not None:
        validator = jsonschema.Draft202012Validator(schema)
        for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
            path = ".".join(str(p) for p in err.absolute_path) or "<root>"
            errors.append(f"{path}: {err.message}")
        return errors

    # Fallback without jsonschema — minimal required-fields check.
    for key in schema.get("required", []):
        if key not in data:
            errors.append(f"<root>: missing required field '{key}'")
    allowed = set(schema.get("properties", {}).get("analysis_scope", {}).get("enum", []))
    if "analysis_scope" in data and data["analysis_scope"] not in allowed:
        errors.append(
            f"analysis_scope: '{data['analysis_scope']}' is not one of {sorted(allowed)}"
        )
    return errors


def load_project(project_root: str | Path) -> tuple[ProjectConfig, ProjectLayout, list[str]]:
    """Load a project from a directory and return (config, layout, errors)."""
    root = Path(project_root)
    config_path = root / "project.yaml"
    if not config_path.is_file():
        raise FileNotFoundError(f"Missing configuration file: {config_path}")

    with config_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    errors = validate_project_config(data)
    config = ProjectConfig.from_dict(data) if not errors else ProjectConfig(
        project_id=str(data.get("project_id", "")),
        name=str(data.get("name", "")),
        version=str(data.get("version", "")),
        created_at=str(data.get("created_at", "")),
        analysis_scope=str(data.get("analysis_scope", "")),
        inputs=dict(data.get("inputs", {})),
        privacy=dict(data.get("privacy", {})),
        ltspice=dict(data.get("ltspice", {})),
        raw=dict(data),
    )
    layout = ProjectLayout.for_root(root)
    return config, layout, errors
