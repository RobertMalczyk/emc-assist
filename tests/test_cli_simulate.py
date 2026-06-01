"""End-to-end CLI tests for the composer and simulate commands."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from emc_assistant.cli import main


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "case_001_buck_conducted_emi"


def _copy_example(tmp_path: Path) -> Path:
    dst = tmp_path / "case_001"
    shutil.copytree(EXAMPLE, dst)
    # Strip gitignored output dirs so tests are hermetic — a prior local
    # pipeline run can leave stale `results/run-*.json` and `generated/*.cir`
    # which would otherwise leak into the test fixture.
    for sub in ("generated", "results", "reports"):
        shutil.rmtree(dst / sub, ignore_errors=True)
    return dst


def test_testbench_compose_creates_cir(tmp_path: Path):
    project = _copy_example(tmp_path)
    rc = main(["testbench", "compose", str(project)])
    assert rc == 0
    cir = project / "generated" / "testbench.cir"
    assert cir.is_file()
    text = cir.read_text(encoding="utf-8")
    assert ".SUBCKT LISN50UH" in text
    assert ".SUBCKT TRACE_RLC" in text
    assert ".step param sweep_corner" in text


def test_simulate_run_dry_run(tmp_path: Path):
    project = _copy_example(tmp_path)
    rc_compose = main(["testbench", "compose", str(project)])
    assert rc_compose == 0
    rc_sim = main(["simulate", "run", str(project), "--mode", "dry-run"])
    assert rc_sim == 0
    results_dir = project / "results"
    runs = list(results_dir.glob("*.json"))
    assert runs, "expected simulation_run.json to be written"
    payload = json.loads(runs[0].read_text(encoding="utf-8"))
    assert payload["status"] == "dry_run"
    assert payload["project_id"] == "case_001_buck_conducted_emi"


def test_simulate_run_requires_compose_first(tmp_path: Path):
    project = _copy_example(tmp_path)
    generated = project / "generated"
    if generated.exists():
        shutil.rmtree(generated)
    rc = main(["simulate", "run", str(project), "--mode", "dry-run"])
    assert rc == 1
