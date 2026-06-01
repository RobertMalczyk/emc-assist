"""End-to-end CLI tests against the example project."""

from __future__ import annotations

import shutil
from pathlib import Path

from emc_assistant.cli import main


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "case_001_buck_conducted_emi"


def _copy_example(tmp_path: Path) -> Path:
    dst = tmp_path / "case_001"
    shutil.copytree(EXAMPLE, dst)
    for sub in ("generated", "results", "reports"):
        shutil.rmtree(dst / sub, ignore_errors=True)
    return dst


def test_cli_version(capsys):
    rc = main(["version"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "emc-assistant" in out


def test_cli_project_validate_ok(tmp_path: Path):
    project = _copy_example(tmp_path)
    rc = main(["project", "validate", str(project)])
    assert rc == 0


def test_cli_project_validate_rejects_invalid(tmp_path: Path, capsys):
    """Validation must actually discriminate — a bad analysis_scope fails."""
    project = _copy_example(tmp_path)
    cfg = project / "project.yaml"
    text = cfg.read_text(encoding="utf-8")
    cfg.write_text(
        text.replace("conducted_emi_dc_dc", "not_a_real_scope"), encoding="utf-8"
    )
    rc = main(["project", "validate", str(project)])
    assert rc == 1
    assert "analysis_scope" in capsys.readouterr().out


def test_cli_report_generate_creates_files(tmp_path: Path):
    project = _copy_example(tmp_path)
    rc = main(["report", "generate", str(project)])
    assert rc == 0
    report = project / "reports" / "report.md"
    rec_json = project / "generated" / "recommendations.json"
    assert report.is_file()
    assert rec_json.is_file()
    contents = report.read_text(encoding="utf-8")
    assert "Disclaimer (pre-compliance)" in contents
    assert "REC-001" in contents
