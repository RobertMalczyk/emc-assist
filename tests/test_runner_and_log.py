"""Tests for the LTspice runner (dry-run) and the .log parser."""

from __future__ import annotations

import json
from pathlib import Path

from emc_assistant.ltspice import LtspiceAdapter, run_simulation
from emc_assistant.results import parse_log


def test_run_simulation_dry_run_without_ltspice(tmp_path: Path):
    netlist = tmp_path / "tb.cir"
    netlist.write_text("* tb\n.tran 0 1m\n.end\n", encoding="utf-8")
    adapter = LtspiceAdapter(executable=None, timeout_seconds=10)
    result = run_simulation(
        adapter=adapter,
        netlist=netlist,
        project_id="proj",
        mode="dry-run",
        output_dir=tmp_path / "results",
    )
    assert result.status == "dry_run"
    assert result.command, "command should be recorded even without LTspice"
    assert any("LTspice" in w for w in result.warnings)
    out_files = list((tmp_path / "results").glob("*.json"))
    assert len(out_files) == 1
    payload = json.loads(out_files[0].read_text(encoding="utf-8"))
    assert payload["status"] == "dry_run"
    assert payload["project_id"] == "proj"


def test_run_simulation_local_run_without_ltspice_marks_failure(tmp_path: Path):
    netlist = tmp_path / "tb.cir"
    netlist.write_text("* tb\n.end\n", encoding="utf-8")
    adapter = LtspiceAdapter(executable=None)
    result = run_simulation(
        adapter=adapter,
        netlist=netlist,
        project_id="proj",
        mode="local-run",
    )
    assert result.status == "failed"
    assert result.errors


def test_parse_log_handles_meas_warnings_errors():
    sample = """
    Circuit: * test
    .step sweep_corner=0
    Warning: convergence helper used
    vout_peak: 5.2000
    vout_avg=4.8e-01
    Total elapsed time: 0.123 seconds.
    """.strip()
    summary = parse_log(sample)
    assert summary.warnings
    assert summary.measurements["vout_peak"] == 5.2
    assert summary.measurements["vout_avg"] == 0.48
    assert summary.total_time_seconds == 0.123
    assert summary.status == "pass"
    assert summary.step_count == 1


def test_parse_log_status_fail_on_error():
    summary = parse_log("Error: matrix is singular")
    assert summary.status == "fail"
    assert summary.errors


def test_parse_log_unknown_when_empty():
    summary = parse_log("")
    assert summary.status == "unknown"


def test_parse_log_handles_measurement_block_single_value():
    sample = (
        "Circuit: * test\n"
        "Measurement: vpeak\n"
        "  MAX(v(meas))=5.2 FROM 0 TO 0.005\n"
        "\n"
        "Total elapsed time: 0.2 seconds.\n"
    )
    summary = parse_log(sample)
    assert summary.measurements["vpeak"] == 5.2
    assert summary.status == "pass"


def test_parse_log_handles_measurement_block_step_sweep():
    sample = (
        "Measurement: vpeak\n"
        "step  MAX(v(meas))\n"
        "   1\t5.20\n"
        "   2\t5.40\n"
        "   3\t5.60\n"
        "\n"
        "Total elapsed time: 0.5 seconds.\n"
    )
    summary = parse_log(sample)
    # Canonical = last step's value.
    assert summary.measurements["vpeak"] == 5.6
    # Per-step entries available too.
    assert summary.measurements["vpeak_step1"] == 5.2
    assert summary.measurements["vpeak_step2"] == 5.4
    assert summary.measurements["vpeak_step3"] == 5.6


def test_parse_log_handles_inline_meas_with_from():
    sample = "vpeak: MAX(v(meas))=2.4 FROM 0 TO 0.005\n"
    summary = parse_log(sample)
    assert summary.measurements["vpeak"] == 2.4


def test_parse_log_handles_simple_with_from_suffix():
    sample = "vrms = 0.35 FROM 0 TO 0.005\n"
    summary = parse_log(sample)
    assert summary.measurements["vrms"] == 0.35


def test_parse_log_multiple_blocks_back_to_back():
    sample = (
        "Measurement: vpeak\n"
        "  MAX(v(meas))=1.0 FROM 0 TO 1\n"
        "Measurement: vrms\n"
        "  RMS(v(meas))=0.7 FROM 0 TO 1\n"
        "\n"
    )
    summary = parse_log(sample)
    assert summary.measurements["vpeak"] == 1.0
    assert summary.measurements["vrms"] == 0.7
