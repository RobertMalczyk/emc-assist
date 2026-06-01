"""Tests for the ``.raw`` inspection / export service layer
(``emc_assistant.service.raw``).

The ``.raw`` *parser* is covered by ``test_raw_parser.py`` and the
quasi-peak entry points by ``test_quasi_peak_detector.py``; the two
remaining service wrappers — ``inspect_raw`` and ``export_raw_csv``,
both exposed on the UI ``Api`` bridge — had no test. This pins their
result shape and their ``ServiceError`` behaviour.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from emc_assistant.service import ServiceError
from emc_assistant.service.raw import (
    RawExportResult,
    RawInspectResult,
    export_raw_csv,
    inspect_raw,
)


def _ascii_raw(path: Path) -> Path:
    """Write a synthetic ASCII ``.raw`` (transient, two voltage traces)."""
    points = [(0.0, 0.0, 0.0), (1e-6, 1.0, -0.5),
              (2e-6, 2.0, -1.0), (3e-6, 1.5, -0.75)]
    header = (
        "Title: * synthetic tran\n"
        "Date: 2026-05-17\n"
        "Plotname: Transient Analysis\n"
        "Flags: real\n"
        "No. Variables: 3\n"
        f"No. Points: {len(points)}\n"
        "Offset: 0\n"
        "Command: synthetic\n"
        "Variables:\n"
        "\t0\ttime\ttime\n"
        "\t1\tV(in)\tvoltage\n"
        "\t2\tV(meas)\tvoltage\n"
        "Values:\n"
    )
    body = []
    for idx, (t, v1, v2) in enumerate(points):
        body += [f"{idx}\t{t}", f"\t{v1}", f"\t{v2}"]
    path.write_text(header + "\n".join(body) + "\n", encoding="utf-8")
    return path


def test_inspect_raw_returns_header_and_trace_list(tmp_path: Path):
    result = inspect_raw(_ascii_raw(tmp_path / "tran.raw"))
    assert isinstance(result, RawInspectResult)
    assert "synthetic" in result.title
    assert result.plotname == "Transient Analysis"
    assert result.flags == ["real"]
    assert result.n_variables == 3
    assert result.n_points == 4
    assert result.axis_min == 0.0
    assert result.axis_max == pytest.approx(3e-6)
    assert [t.name for t in result.traces] == ["time", "V(in)", "V(meas)"]
    assert [t.kind for t in result.traces] == ["time", "voltage", "voltage"]
    assert [t.index for t in result.traces] == [0, 1, 2]


def test_inspect_raw_missing_file_raises_service_error(tmp_path: Path):
    with pytest.raises(ServiceError, match="File not found"):
        inspect_raw(tmp_path / "absent.raw")


def test_inspect_raw_unsupported_format_raises_service_error(tmp_path: Path):
    """A ``fastaccess`` binary is unsupported — the service must surface
    that as a ServiceError with exit code 2, not a raw parser exception."""
    header = (
        "Title: * fastaccess\n"
        "Plotname: Transient\n"
        "Flags: real fastaccess\n"
        "No. Variables: 2\n"
        "No. Points: 1\n"
        "Variables:\n"
        "\t0\ttime\ttime\n"
        "\t1\tV(x)\tvoltage\n"
        "Binary:\n"
    ).encode("utf-16-le")
    p = tmp_path / "fa.raw"
    p.write_bytes(b"\xff\xfe" + header + struct.pack("<dd", 0.0, 1.0))
    with pytest.raises(ServiceError) as excinfo:
        inspect_raw(p)
    assert excinfo.value.exit_code == 2


def test_export_raw_csv_writes_selected_traces(tmp_path: Path):
    raw = _ascii_raw(tmp_path / "tran.raw")
    out = tmp_path / "export.csv"
    result = export_raw_csv(raw, ["V(in)"], out)
    assert isinstance(result, RawExportResult)
    assert result.output_path == out
    assert result.traces == ["V(in)"]
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == "time,V(in)"
    assert len(lines) == 1 + 4  # header + 4 points


def test_export_raw_csv_empty_selection_exports_every_trace(tmp_path: Path):
    """An empty ``traces`` list exports every trace except the axis."""
    raw = _ascii_raw(tmp_path / "tran.raw")
    out = tmp_path / "all.csv"
    result = export_raw_csv(raw, [], out)
    assert result.traces == ["V(in)", "V(meas)"]
    assert out.read_text(encoding="utf-8").splitlines()[0] == "time,V(in),V(meas)"


def test_export_raw_csv_missing_file_raises_service_error(tmp_path: Path):
    with pytest.raises(ServiceError, match="File not found"):
        export_raw_csv(tmp_path / "absent.raw", [], tmp_path / "x.csv")
