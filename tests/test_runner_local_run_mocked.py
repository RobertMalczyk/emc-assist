"""End-to-end test of the local-run path with a mocked LTspice executable.

We do not require a real LTspice installation in CI. Instead we
monkeypatch ``subprocess.run`` so the call to ``LTspice -b -Run …``
becomes a Python function that writes synthetic ``.raw`` and ``.log``
files next to the netlist. The rest of the runner — return-code
handling, ``.raw`` parsing, metric extraction, ``simulation_run.json``
emission — is exercised exactly as in production.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from emc_assistant.cli import main
from emc_assistant.ltspice import LtspiceAdapter, run_simulation


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "case_001_buck_conducted_emi"


def _ascii_raw(netlist_dir: Path, netlist_stem: str) -> Path:
    """Write a synthetic transient ASCII `.raw` next to the netlist."""
    points = [
        (0.0, 0.0, 0.0),
        (2.5e-6, 0.0, 0.2),
        (5e-6, 0.0, -0.2),
        (7.5e-6, 0.0, 0.5),
        (1e-5, 0.0, -0.5),
    ]
    n = len(points)
    raw_text = (
        "Title: * mocked transient\n"
        "Date: 2026-05-13\n"
        "Plotname: Transient Analysis\n"
        "Flags: real\n"
        "No. Variables: 3\n"
        f"No. Points: {n}\n"
        "Offset: 0\n"
        "Command: mocked\n"
        "Variables:\n"
        "\t0\ttime\ttime\n"
        "\t1\tV(in)\tvoltage\n"
        "\t2\tV(MEAS)\tvoltage\n"
        "Values:\n"
    )
    rows: list[str] = []
    for idx, (t, vin, vmeas) in enumerate(points):
        rows.append(f"{idx}\t{t}")
        rows.append(f"\t{vin}")
        rows.append(f"\t{vmeas}")
    raw_path = netlist_dir / f"{netlist_stem}.raw"
    raw_path.write_text(raw_text + "\n".join(rows) + "\n", encoding="utf-8")
    return raw_path


def _meas_log(netlist_dir: Path, netlist_stem: str) -> Path:
    """Write a synthetic `.log` carrying typical LTspice `.meas` output."""
    log_text = (
        "Circuit: * mocked\n"
        ".step sweep_corner=1\n"
        "Measurement: vpeak\n"
        "  MAX(v(meas))=0.5 FROM 0 TO 1e-05\n"
        "Measurement: vrms\n"
        "  RMS(v(meas))=0.31 FROM 0 TO 1e-05\n"
        "\n"
        "Total elapsed time: 0.012 seconds.\n"
    )
    log_path = netlist_dir / f"{netlist_stem}.log"
    log_path.write_text(log_text, encoding="utf-8")
    return log_path


class _FakeProc:
    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = stderr


def _make_fake_run(emit_artefacts: bool = True):
    """Return a substitute for ``subprocess.run`` that pretends to be LTspice."""

    def _fake_run(command, *args, **kwargs):
        # command = [<exe>, "-b", "-Run", "<netlist>"]
        netlist = Path(command[-1])
        if emit_artefacts and netlist.is_file():
            _ascii_raw(netlist.parent, netlist.stem)
            _meas_log(netlist.parent, netlist.stem)
        return _FakeProc(returncode=0)

    return _fake_run


def _make_failing_run(stderr: str):
    def _fake_run(command, *args, **kwargs):
        return _FakeProc(returncode=2, stderr=stderr)

    return _fake_run


def test_local_run_with_mocked_ltspice_populates_metrics(tmp_path: Path, monkeypatch):
    netlist = tmp_path / "tb.cir"
    netlist.write_text("* tb\n.tran 0 1e-5\n.end\n", encoding="utf-8")
    fake_exe = tmp_path / "ltspice_stub.exe"
    fake_exe.write_text("# stub", encoding="utf-8")

    monkeypatch.setattr(subprocess, "run", _make_fake_run())
    adapter = LtspiceAdapter(executable=fake_exe, timeout_seconds=5)
    result = run_simulation(
        adapter=adapter,
        netlist=netlist,
        project_id="proj",
        mode="local-run",
    )

    assert result.status == "completed"
    assert result.return_code == 0
    # metrics{} was filled by parse_raw + summarize_default_metrics.
    assert any(k.startswith("v_meas_") for k in result.metrics), result.metrics
    assert result.metrics["v_meas_peak"] == 0.5
    assert "axis_min" in result.metrics
    # Artefact paths are real files now.
    assert Path(result.artifacts["raw"]).is_file()
    assert Path(result.artifacts["log"]).is_file()


def test_local_run_failure_records_stderr(tmp_path: Path, monkeypatch):
    netlist = tmp_path / "tb.cir"
    netlist.write_text("* tb\n.tran 0 1e-5\n.end\n", encoding="utf-8")
    fake_exe = tmp_path / "ltspice_stub.exe"
    fake_exe.write_text("# stub", encoding="utf-8")

    monkeypatch.setattr(
        subprocess, "run", _make_failing_run("Singular matrix in node X")
    )
    adapter = LtspiceAdapter(executable=fake_exe)
    result = run_simulation(
        adapter=adapter,
        netlist=netlist,
        project_id="proj",
        mode="local-run",
    )
    assert result.status == "failed"
    assert result.return_code == 2
    assert any("Singular matrix" in e for e in result.errors)
    # Classified hint is appended (convergence).
    assert any("[convergence]" in e for e in result.errors)


def test_local_run_classifies_missing_model(tmp_path: Path, monkeypatch):
    netlist = tmp_path / "tb.cir"
    netlist.write_text("* tb\n.end\n", encoding="utf-8")
    fake_exe = tmp_path / "stub.exe"
    fake_exe.write_text("# stub", encoding="utf-8")
    monkeypatch.setattr(
        subprocess,
        "run",
        _make_failing_run("Unknown subcircuit called FOO"),
    )
    adapter = LtspiceAdapter(executable=fake_exe)
    result = run_simulation(
        adapter=adapter,
        netlist=netlist,
        project_id="proj",
        mode="local-run",
    )
    assert result.status == "failed"
    assert any("[missing_model]" in e for e in result.errors)


def test_local_run_classifies_file_not_found(tmp_path: Path, monkeypatch):
    # LTspice prints "File not found." when an `.include` path can't be
    # resolved. That diagnostic must classify as `[missing_model]` so the
    # CLI surfaces a helpful hint instead of an opaque "failed".
    netlist = tmp_path / "tb.cir"
    netlist.write_text("* tb\n.include nope.cir\n.end\n", encoding="utf-8")
    fake_exe = tmp_path / "stub.exe"
    fake_exe.write_text("# stub", encoding="utf-8")
    monkeypatch.setattr(
        subprocess,
        "run",
        _make_failing_run("testbench.cir(2): File not found."),
    )
    adapter = LtspiceAdapter(executable=fake_exe)
    result = run_simulation(
        adapter=adapter,
        netlist=netlist,
        project_id="proj",
        mode="local-run",
    )
    assert result.status == "failed"
    assert any("[missing_model]" in e for e in result.errors)


def test_local_run_pulls_meas_from_log(tmp_path: Path, monkeypatch):
    """When LTspice produced a `.log` with .meas but no `.raw`,
    metrics must still flow into the run result."""
    netlist = tmp_path / "tb.cir"
    netlist.write_text("* tb\n.tran 0 1e-5\n.end\n", encoding="utf-8")
    fake_exe = tmp_path / "stub.exe"
    fake_exe.write_text("# stub", encoding="utf-8")

    def _fake_run(command, *args, **kwargs):
        nl = Path(command[-1])
        _meas_log(nl.parent, nl.stem)  # only the log, no .raw
        return _FakeProc(returncode=0)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    adapter = LtspiceAdapter(executable=fake_exe)
    result = run_simulation(
        adapter=adapter,
        netlist=netlist,
        project_id="proj",
        mode="local-run",
    )
    assert result.status == "completed"
    # Meas values came from `.log` (no `.raw` produced).
    assert result.metrics.get("vpeak") == 0.5
    assert result.metrics.get("vrms") == 0.31


def test_pipeline_local_run_with_mocked_ltspice_fills_report(tmp_path: Path, monkeypatch):
    """End-to-end: pipeline run --mode local-run with a fake LTspice fills the
    Measurements section and the ranking."""
    project = tmp_path / "case_001"
    shutil.copytree(EXAMPLE, project)
    for sub in ("generated", "results", "reports"):
        shutil.rmtree(project / sub, ignore_errors=True)

    fake_exe = tmp_path / "ltspice_stub.exe"
    fake_exe.write_text("# stub", encoding="utf-8")
    monkeypatch.setenv("LTSPICE_PATH", str(fake_exe))
    monkeypatch.setattr(subprocess, "run", _make_fake_run())

    rc = main([
        "pipeline",
        "run",
        str(project),
        "--mode",
        "local-run",
        "--rank-metric",
        "v_meas_peak",
    ])
    assert rc == 0

    # All variant simulation_run.json files now carry real metrics.
    var_dir = project / "results" / "variants"
    runs = list(var_dir.glob("*.json"))
    assert runs, "expected variant results"
    sample = json.loads(runs[0].read_text(encoding="utf-8"))
    assert sample["status"] == "completed"
    assert sample["metrics"], "metrics{} should be populated under local-run"

    report = (project / "reports" / "report.md").read_text(encoding="utf-8")
    # Measurements table no longer shows the placeholder; ranking renders.
    assert "No metrics — no `.raw` files detected" not in report
    assert "Variant ranking by `v_meas_peak`" in report
    assert "v_meas_peak" in report
