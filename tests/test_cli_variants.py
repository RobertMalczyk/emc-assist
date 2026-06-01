"""End-to-end CLI tests for variants and the ranked report."""

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


def test_variants_compose_creates_cir_per_variant(tmp_path: Path):
    project = _copy_example(tmp_path)
    rc = main(["variants", "compose", str(project)])
    assert rc == 0
    var_dir = project / "generated" / "variants"
    assert (var_dir / "variants.json").is_file()
    manifest = json.loads((var_dir / "variants.json").read_text(encoding="utf-8"))
    assert len(manifest) >= 1
    assert manifest[0]["label"] == "baseline"
    for entry in manifest:
        assert Path(entry["cir"]).is_file()


def test_variants_run_dry_run_writes_results(tmp_path: Path):
    project = _copy_example(tmp_path)
    assert main(["variants", "compose", str(project)]) == 0
    rc = main(["variants", "run", str(project), "--mode", "dry-run"])
    assert rc == 0
    out_dir = project / "results" / "variants"
    runs = list(out_dir.glob("*.json"))
    assert runs
    payload = json.loads(runs[0].read_text(encoding="utf-8"))
    assert payload["status"] == "dry_run"
    assert "variant_label" in payload


def test_report_with_ranking_renders_section(tmp_path: Path):
    project = _copy_example(tmp_path)
    assert main(["variants", "compose", str(project)]) == 0
    assert main(["variants", "run", str(project), "--mode", "dry-run"]) == 0

    # Inject synthetic metrics — dry-run does not produce them.
    out_dir = project / "results" / "variants"
    metric_values = {"baseline": 1.0, "par-trace-R-20x1-1oz-min": 0.5}
    for path in out_dir.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        label = payload.get("variant_label", path.stem)
        if label in metric_values:
            payload["metrics"] = {"vpeak": metric_values[label]}
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    rc = main([
        "report",
        "generate",
        str(project),
        "--rank-metric",
        "vpeak",
    ])
    assert rc == 0
    report = (project / "reports" / "report.md").read_text(encoding="utf-8")
    assert "Variants (min/typ/max sweep)" in report
    assert "Variant ranking by `vpeak`" in report
    # baseline = 1.0, var-min = 0.5 → var-min wins when lower is better.
    assert "par-trace-R-20x1-1oz-min" in report
