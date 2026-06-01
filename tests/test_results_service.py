"""Tests for service.report.load_results — the Results-screen aggregator.

Exercises the metrics/ranking path with synthetic variant artifacts (no
LTspice), plus the graceful empty states.
"""

from __future__ import annotations

import json
from pathlib import Path

from emc_assistant.service import report as report_service
from emc_assistant.service.options import CommandOptions
from emc_assistant.service.project import create_project

_PEAK = "v_meas_band_peak_dbuv_150000_30000000"
_MARGIN = "v_meas_qp_worst_margin_db"


def _write_variant(layout_dir: Path, label: str, peak: float, margin: float, **extra):
    p = layout_dir / "results" / "variants"
    p.mkdir(parents=True, exist_ok=True)
    metrics = {_PEAK: peak, _MARGIN: margin, "dm_peak": 3.0, "cm_peak": 0.0, **extra}
    (p / f"{label}.json").write_text(
        json.dumps({"variant_label": label, "status": "completed", "metrics": metrics}),
        encoding="utf-8",
    )


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    create_project(str(root))
    return root


def test_load_results_empty_when_nothing_run(tmp_path: Path):
    view = report_service.load_results(str(_project(tmp_path)))
    assert view.diagnostic is None
    assert view.has_metrics is False
    assert view.ranking == []
    assert view.baseline["peak_dbuv"] is None


def test_load_results_ranks_variants_by_band_peak(tmp_path: Path):
    root = _project(tmp_path)
    _write_variant(root, "baseline", peak=65.0, margin=8.0)
    _write_variant(root, "trace-L-max", peak=70.0, margin=3.0)   # worst
    _write_variant(root, "trace-L-min", peak=63.0, margin=10.0)  # best

    view = report_service.load_results(str(root))
    assert view.has_metrics is True
    # Higher band peak = worse = rank 1 (lower_is_better=False).
    assert view.ranking[0]["label"] == "trace-L-max"
    assert view.ranking[0]["rank"] == 1
    assert view.ranking[0]["peak_dbuv"] == 70.0
    assert view.ranking[0]["margin_db"] == 3.0
    # Span = max - min band peak across variants.
    assert abs(view.baseline["span_db"] - (70.0 - 63.0)) < 1e-9
    # Baseline headline metrics surfaced.
    assert view.baseline["peak_dbuv"] == 65.0
    assert view.baseline["margin_db"] == 8.0


def test_load_results_reads_diagnostic(tmp_path: Path):
    root = _project(tmp_path)
    diag = {"title": "T", "narrative": "N", "dominant_issue": "D",
            "confidence": 0.6, "llm_generated": False, "limitations": []}
    (root / "results").mkdir(parents=True, exist_ok=True)
    (root / "results" / "diagnostic.json").write_text(json.dumps(diag), encoding="utf-8")

    view = report_service.load_results(str(root))
    assert view.diagnostic["title"] == "T"
    assert view.diagnostic["confidence"] == 0.6
