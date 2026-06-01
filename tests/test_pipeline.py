"""End-to-end test of `pipeline run` against the golden buck example."""

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
    for sub in ("generated", "results", "reports"):
        shutil.rmtree(dst / sub, ignore_errors=True)
    return dst


def test_pipeline_run_dry_run_end_to_end(tmp_path: Path):
    project = _copy_example(tmp_path)
    rc = main(["pipeline", "run", str(project), "--mode", "dry-run"])
    assert rc == 0
    parasitics = project / "generated" / "parasitics.json"
    assert parasitics.is_file()
    assert (project / "generated" / "testbench.cir").is_file()
    var_dir = project / "generated" / "variants"
    assert (var_dir / "variants.json").is_file()
    assert any(var_dir.glob("baseline.cir"))
    results = project / "results" / "variants"
    runs = list(results.glob("*.json"))
    assert runs, "expected variant results to be written"
    payload = json.loads(runs[0].read_text(encoding="utf-8"))
    assert payload["status"] == "dry_run"
    report = (project / "reports" / "report.md").read_text(encoding="utf-8")
    assert "Disclaimer (pre-compliance)" in report
    assert "Estimated parasitics" in report
    assert "Variants (min/typ/max sweep)" in report
    assert "Measurements (from `.raw` / `simulation_run.json`)" in report
    assert "Recommendations" in report


def test_pipeline_uses_buck_demo_via_fragment(tmp_path: Path):
    project = _copy_example(tmp_path)
    assert main(["pipeline", "run", str(project), "--mode", "dry-run"]) == 0
    fragment = project / "generated" / "user_circuit_fragment.cir"
    assert fragment.is_file()
    text = fragment.read_text(encoding="utf-8")
    forbidden_heads = (".tran", ".end", ".step", ".ac", ".dc", ".options")
    for line in text.splitlines():
        head = line.lstrip()
        if head.startswith("*"):
            continue
        low = head.lower()
        for forbidden in forbidden_heads:
            assert not low.startswith(forbidden), f"Fragment has forbidden directive: {line!r}"
    # The buck components must remain (inductor L1 and switch S1).
    assert "L1" in text
    assert "S1" in text


def test_raw_inspect_and_export_via_cli(tmp_path: Path, capsys):
    # Build a synthetic ASCII `.raw` and exercise both raw subcommands.
    raw_path = tmp_path / "synth.raw"
    raw_path.write_text(
        "Title: synth\n"
        "Plotname: Transient Analysis\n"
        "Flags: real\n"
        "No. Variables: 2\n"
        "No. Points: 3\n"
        "Variables:\n"
        "\t0\ttime\ttime\n"
        "\t1\tV(out)\tvoltage\n"
        "Values:\n"
        "0\t0.0\n"
        "\t1.0\n"
        "1\t1e-6\n"
        "\t0.5\n"
        "2\t2e-6\n"
        "\t-0.25\n",
        encoding="utf-8",
    )
    rc = main(["raw", "inspect", str(raw_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Variables: 2" in out
    assert "V(out)" in out

    csv_path = tmp_path / "out.csv"
    rc = main(["raw", "export-csv", str(raw_path), "--output", str(csv_path), "--trace", "V(out)"])
    assert rc == 0
    csv_text = csv_path.read_text(encoding="utf-8")
    assert csv_text.startswith("time,V(out)")
    assert "1e-06" in csv_text or "1.000000e-06" in csv_text
