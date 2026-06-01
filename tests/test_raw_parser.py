"""Tests for the LTspice `.raw` parser (ASCII + binary)."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from emc_assistant.results.raw_parser import (
    UnsupportedRawFormat,
    extract_to_csv,
    list_traces,
    parse_raw,
    primary_step_range,
    step_segment_bounds,
)


def _ascii_raw_tran() -> str:
    """Synthetic ASCII `.raw` in LTspice style with two traces."""
    points = [
        (0.0, 0.0, 0.0),
        (1e-6, 1.0, -0.5),
        (2e-6, 2.0, -1.0),
        (3e-6, 1.5, -0.75),
    ]
    n_points = len(points)
    header = (
        "Title: * synthetic tran\n"
        "Date: 2026-05-13\n"
        "Plotname: Transient Analysis\n"
        "Flags: real\n"
        "No. Variables: 3\n"
        f"No. Points: {n_points}\n"
        "Offset: 0\n"
        "Command: synthetic\n"
        "Variables:\n"
        "\t0\ttime\ttime\n"
        "\t1\tV(in)\tvoltage\n"
        "\t2\tV(meas)\tvoltage\n"
        "Values:\n"
    )
    body_lines = []
    for idx, (t, v1, v2) in enumerate(points):
        body_lines.append(f"{idx}\t{t}")
        body_lines.append(f"\t{v1}")
        body_lines.append(f"\t{v2}")
    return header + "\n".join(body_lines) + "\n"


def _binary_raw_tran() -> bytes:
    """Synthetic binary `.raw` (real)."""
    points = [
        (0.0, 0.0, 0.0),
        (1e-6, 1.0, -0.5),
        (2e-6, 2.0, -1.0),
    ]
    header = (
        "Title: * binary tran\n"
        "Date: 2026-05-13\n"
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
        "Binary:\n"
    ).encode("utf-16-le")
    body = b""
    for t, v1, v2 in points:
        body += struct.pack("<ddd", t, v1, v2)
    return b"\xff\xfe" + header + body


def _binary_raw_ac() -> bytes:
    """Synthetic complex binary `.raw` (e.g. .ac)."""
    points = [
        (1e3, 0.5 + 0j, 0.1 + 0.05j),
        (10e3, 0.4 + 0j, 0.2 - 0.1j),
        (100e3, 0.3 + 0j, 0.05 + 0.02j),
    ]
    header = (
        "Title: * ac\n"
        "Date: 2026-05-13\n"
        "Plotname: AC Analysis\n"
        "Flags: complex\n"
        "No. Variables: 3\n"
        f"No. Points: {len(points)}\n"
        "Variables:\n"
        "\t0\tfrequency\tfrequency\n"
        "\t1\tV(in)\tvoltage\n"
        "\t2\tV(out)\tvoltage\n"
        "Binary:\n"
    ).encode("utf-16-le")
    body = b""
    for f, v1, v2 in points:
        body += struct.pack(
            "<dddddd",
            f.real, f.imag,
            v1.real, v1.imag,
            v2.real, v2.imag,
        )
    return b"\xff\xfe" + header + body


def test_parse_ascii_raw(tmp_path: Path):
    p = tmp_path / "tran.raw"
    p.write_text(_ascii_raw_tran(), encoding="utf-8")
    raw = parse_raw(p)
    assert raw.header.n_variables == 3
    assert raw.header.n_points == 4
    assert raw.axis == [0.0, 1e-6, 2e-6, 3e-6]
    assert raw.traces["V(in)"] == [0.0, 1.0, 2.0, 1.5]
    assert raw.traces["V(meas)"] == [0.0, -0.5, -1.0, -0.75]
    assert raw.is_complex is False


def test_parse_binary_tran(tmp_path: Path):
    p = tmp_path / "tran.raw"
    p.write_bytes(_binary_raw_tran())
    raw = parse_raw(p)
    assert raw.header.is_binary
    assert raw.header.n_points == 3
    assert raw.axis == pytest.approx([0.0, 1e-6, 2e-6])
    assert raw.traces["V(in)"] == pytest.approx([0.0, 1.0, 2.0])
    assert raw.traces["V(meas)"] == pytest.approx([0.0, -0.5, -1.0])


def test_parse_binary_ac_complex(tmp_path: Path):
    p = tmp_path / "ac.raw"
    p.write_bytes(_binary_raw_ac())
    raw = parse_raw(p)
    assert raw.is_complex
    assert raw.traces_complex is not None
    # |V(out)| at 10 kHz = |0.2 - 0.1j| = sqrt(0.05)
    assert raw.traces["V(out)"][1] == pytest.approx((0.05) ** 0.5)
    # Axis is magnitude (Im=0 → |f| = f).
    assert raw.axis == pytest.approx([1e3, 10e3, 100e3])


def test_list_traces(tmp_path: Path):
    p = tmp_path / "tran.raw"
    p.write_text(_ascii_raw_tran(), encoding="utf-8")
    names = list_traces(p)
    assert names == ["time", "V(in)", "V(meas)"]


def test_extract_to_csv(tmp_path: Path):
    p = tmp_path / "tran.raw"
    p.write_text(_ascii_raw_tran(), encoding="utf-8")
    raw = parse_raw(p)
    out = tmp_path / "export.csv"
    extract_to_csv(raw, ["V(in)", "V(meas)"], out)
    text = out.read_text(encoding="utf-8")
    lines = text.strip().splitlines()
    assert lines[0] == "time,V(in),V(meas)"
    assert len(lines) == 1 + raw.header.n_points


def test_extract_to_csv_rejects_unknown_trace(tmp_path: Path):
    p = tmp_path / "tran.raw"
    p.write_text(_ascii_raw_tran(), encoding="utf-8")
    raw = parse_raw(p)
    with pytest.raises(KeyError):
        extract_to_csv(raw, ["NOT_THERE"], tmp_path / "x.csv")


def test_parse_binary_tolerates_over_reported_n_points(tmp_path: Path):
    # LTspice with `.step` + adaptive timestep can declare more `No. Points`
    # in the header than the body actually contains. The parser must use
    # min(declared, actual) instead of raising UnsupportedRawFormat.
    actual_points = [
        (0.0, 0.0, 0.0),
        (1e-6, 1.0, -0.5),
        (2e-6, 2.0, -1.0),
    ]
    declared = 999  # far above what the body carries
    header = (
        "Title: * over-reported tran\n"
        "Date: 2026-05-13\n"
        "Plotname: Transient Analysis\n"
        "Flags: real\n"
        "No. Variables: 3\n"
        f"No. Points: {declared}\n"
        "Offset: 0\n"
        "Command: synthetic\n"
        "Variables:\n"
        "\t0\ttime\ttime\n"
        "\t1\tV(in)\tvoltage\n"
        "\t2\tV(meas)\tvoltage\n"
        "Binary:\n"
    ).encode("utf-16-le")
    body = b""
    for t, v1, v2 in actual_points:
        body += struct.pack("<ddd", t, v1, v2)
    p = tmp_path / "trunc.raw"
    p.write_bytes(b"\xff\xfe" + header + body)

    raw = parse_raw(p)
    assert raw.header.n_points == len(actual_points)
    assert raw.axis == pytest.approx([0.0, 1e-6, 2e-6])
    assert raw.traces["V(meas)"] == pytest.approx([0.0, -0.5, -1.0])


def test_fastaccess_is_unsupported(tmp_path: Path):
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
    body = struct.pack("<dd", 0.0, 1.0)
    p = tmp_path / "fa.raw"
    p.write_bytes(b"\xff\xfe" + header + body)
    with pytest.raises(UnsupportedRawFormat):
        parse_raw(p)


def test_short_binary_degrades_to_actual_points(tmp_path: Path):
    # Header over-reports `No. Points`; the parser must clamp to the actual
    # body and return what records are present rather than raising.
    header = (
        "Title: * short\n"
        "Plotname: Transient\n"
        "Flags: real\n"
        "No. Variables: 2\n"
        "No. Points: 5\n"
        "Variables:\n"
        "\t0\ttime\ttime\n"
        "\t1\tV(x)\tvoltage\n"
        "Binary:\n"
    ).encode("utf-16-le")
    body = struct.pack("<dd", 0.0, 1.0)  # only one point, header expects five
    p = tmp_path / "short.raw"
    p.write_bytes(b"\xff\xfe" + header + body)
    raw = parse_raw(p)
    assert raw.header.n_points == 1
    assert raw.axis == pytest.approx([0.0])
    assert raw.traces["V(x)"] == pytest.approx([1.0])


def test_parse_compressed_real_binary(tmp_path: Path):
    # Modern LTspice writes `real forward` binaries with time as double and
    # data variables as float — half-size records compared to the legacy
    # all-doubles layout.
    points = [
        (0.0, 0.0, 0.0),
        (1e-6, 1.0, -0.5),
        (2e-6, 2.0, -1.0),
        (3e-6, 1.5, -0.75),
    ]
    header = (
        "Title: * compressed tran\n"
        "Date: 2026-05-14\n"
        "Plotname: Transient Analysis\n"
        "Flags: real forward\n"
        "No. Variables: 3\n"
        f"No. Points: {len(points)}\n"
        "Offset: 0\n"
        "Command: synthetic\n"
        "Variables:\n"
        "\t0\ttime\ttime\n"
        "\t1\tV(in)\tvoltage\n"
        "\t2\tV(meas)\tvoltage\n"
        "Binary:\n"
    ).encode("utf-16-le")
    body = b""
    for t, v1, v2 in points:
        # 8 B double for axis, 4 B float for each data variable.
        body += struct.pack("<dff", t, v1, v2)
    p = tmp_path / "compressed.raw"
    p.write_bytes(b"\xff\xfe" + header + body)
    raw = parse_raw(p)
    assert raw.axis == pytest.approx([0.0, 1e-6, 2e-6, 3e-6])
    assert raw.traces["V(in)"] == pytest.approx([0.0, 1.0, 2.0, 1.5])
    assert raw.traces["V(meas)"] == pytest.approx([0.0, -0.5, -1.0, -0.75])


def test_compressed_real_survives_trailing_partial_record(tmp_path: Path):
    # Regression for the real-world case_002 bug: a compressed-real `.raw` whose
    # body ends in a *partial* record (an interrupted / adaptive-step run) used
    # to defeat the remainder-based layout heuristic — the legacy all-double
    # stride happened to divide the body more cleanly, so the parser mis-strided
    # the entire file and produced a garbage, non-monotonic axis (→ NaN
    # downstream → blank charts). The declared `No. Points` now disambiguates:
    # 4 compressed points fit; the full (all-double) layout would imply only 3.
    points = [
        (0.0, 0.0, 0.0),
        (1e-6, 1.0, -0.5),
        (2e-6, 2.0, -1.0),
        (3e-6, 1.5, -0.75),
    ]
    header = (
        "Title: * interrupted compressed tran\n"
        "Plotname: Transient Analysis\n"
        "Flags: real forward\n"
        "No. Variables: 3\n"
        f"No. Points: {len(points)}\n"
        "Variables:\n"
        "\t0\ttime\ttime\n"
        "\t1\tV(in)\tvoltage\n"
        "\t2\tV(meas)\tvoltage\n"
        "Binary:\n"
    ).encode("utf-16-le")
    body = b"".join(struct.pack("<dff", t, v1, v2) for t, v1, v2 in points)
    body += b"\x00" * 8  # an incomplete trailing record (interrupted write)
    # The trap: with this body the full (24 B) stride divides *cleaner* than the
    # true compressed (16 B) stride, so the old remainder heuristic chose full.
    assert len(body) % 24 < len(body) % 16
    p = tmp_path / "interrupted.raw"
    p.write_bytes(b"\xff\xfe" + header + body)
    raw = parse_raw(p)
    assert raw.header.n_points == 4
    assert raw.axis == pytest.approx([0.0, 1e-6, 2e-6, 3e-6])  # monotonic, not garbage
    assert raw.traces["V(in)"] == pytest.approx([0.0, 1.0, 2.0, 1.5])
    assert raw.traces["V(meas)"] == pytest.approx([0.0, -0.5, -1.0, -0.75])


def test_empty_binary_body_raises(tmp_path: Path):
    # Truly empty body — not even one full record fits → genuine error.
    header = (
        "Title: * empty\n"
        "Plotname: Transient\n"
        "Flags: real\n"
        "No. Variables: 2\n"
        "No. Points: 5\n"
        "Variables:\n"
        "\t0\ttime\ttime\n"
        "\t1\tV(x)\tvoltage\n"
        "Binary:\n"
    ).encode("utf-16-le")
    p = tmp_path / "empty.raw"
    p.write_bytes(b"\xff\xfe" + header)
    with pytest.raises(UnsupportedRawFormat):
        parse_raw(p)


def _binary_raw_stepped() -> bytes:
    """Synthetic stepped binary `.raw`: three corner transients (the
    ``sweep_corner`` 0/1/2 sweep) concatenated, each a 0→2e-6 s ramp. The typ
    corner (step 1) carries a distinct V(meas) so we can prove it is the one
    selected."""
    step = [(0.0, 0.0), (1e-6, 1.0), (2e-6, 2.0)]
    corners = [10.0, 20.0, 30.0]  # V(meas) flat level per corner: min/typ/max
    points = [(t, vin, lvl) for lvl in corners for (t, vin) in step]
    header = (
        "Title: * stepped tran\n"
        "Plotname: Transient Analysis\n"
        "Flags: real forward stepped\n"
        "No. Variables: 3\n"
        f"No. Points: {len(points)}\n"
        "Offset: 0\n"
        "Variables:\n"
        "\t0\ttime\ttime\n"
        "\t1\tV(in)\tvoltage\n"
        "\t2\tV(meas)\tvoltage\n"
        "Binary:\n"
    ).encode("utf-16-le")
    body = b"".join(struct.pack("<ddd", t, v1, v2) for t, v1, v2 in points)
    return b"\xff\xfe" + header + body


def test_step_segment_bounds_splits_on_time_reset():
    # Non-stepped → one whole segment.
    assert step_segment_bounds([0.0, 1.0, 2.0, 3.0]) == [(0, 4)]
    # Three steps (axis resets twice) → three segments.
    assert step_segment_bounds([0, 1, 2, 0, 1, 2, 0, 1, 2]) == [(0, 3), (3, 6), (6, 9)]
    # Two steps.
    assert step_segment_bounds([0, 1, 0, 1]) == [(0, 2), (2, 4)]
    # Empty.
    assert step_segment_bounds([]) == []


def test_primary_step_range_picks_typ_corner():
    # 0=min, 1=typ, 2=max → the middle segment is typ.
    assert primary_step_range([0, 1, 2, 0, 1, 2, 0, 1, 2]) == (3, 6)
    # Non-stepped → the whole axis.
    assert primary_step_range([0.0, 1.0, 2.0]) == (0, 3)
    # Empty → degenerate.
    assert primary_step_range([]) == (0, 0)


def test_stepped_raw_typ_step_isolates_one_transient(tmp_path: Path):
    """End-to-end on a parsed stepped `.raw`: the typ slice yields a single,
    time-monotonic transient (no wrap), carrying the typ corner's values."""
    p = tmp_path / "stepped.raw"
    p.write_bytes(_binary_raw_stepped())
    raw = parse_raw(p)
    assert "stepped" in raw.header.flags
    assert len(raw.axis) == 9  # all three corners concatenated
    i0, i1 = primary_step_range(raw.axis)
    axis_seg = raw.axis[i0:i1]
    meas_seg = raw.traces["V(meas)"][i0:i1]
    assert axis_seg == pytest.approx([0.0, 1e-6, 2e-6])  # one clean transient
    assert all(axis_seg[k] >= axis_seg[k - 1] for k in range(1, len(axis_seg)))
    assert meas_seg == pytest.approx([20.0, 20.0, 20.0])  # the typ corner
