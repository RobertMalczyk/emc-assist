"""Tests for the project model and project.yaml validation."""

from __future__ import annotations

from pathlib import Path

import yaml

from emc_assistant.project.model import (
    ProjectLayout,
    load_project,
    validate_project_config,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "case_001_buck_conducted_emi"


def test_example_project_loads_without_errors():
    config, layout, errors = load_project(EXAMPLE)
    assert errors == [], errors
    assert config.project_id == "case_001_buck_conducted_emi"
    assert config.analysis_scope == "conducted_emi_dc_dc"
    assert isinstance(layout, ProjectLayout)
    assert layout.input_dir.is_dir()


def test_validation_reports_missing_required(tmp_path: Path):
    bad = {
        "project_id": "x",
        "name": "x",
        # Missing: version, created_at, inputs, analysis_scope.
    }
    errors = validate_project_config(bad)
    assert errors, "expected validation errors"
    joined = " ".join(errors).lower()
    assert "version" in joined or "required" in joined


def test_validation_rejects_invalid_scope():
    cfg = {
        "project_id": "x",
        "name": "x",
        "version": "0.0.1",
        "created_at": "2026-01-01",
        "analysis_scope": "not_a_real_scope",
        "inputs": {},
    }
    errors = validate_project_config(cfg)
    assert any("analysis_scope" in e for e in errors), errors


def test_project_layout_creates_dirs(tmp_path: Path):
    layout = ProjectLayout.for_root(tmp_path)
    layout.ensure_dirs()
    assert layout.input_dir.is_dir()
    assert layout.generated_dir.is_dir()
    assert layout.results_dir.is_dir()
    assert layout.reports_dir.is_dir()


def test_project_yaml_in_example_is_well_formed():
    with (EXAMPLE / "project.yaml").open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    errors = validate_project_config(data)
    assert errors == [], errors
