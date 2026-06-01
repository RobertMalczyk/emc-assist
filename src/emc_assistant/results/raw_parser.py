"""Minimal LTspice ``.raw`` parser.

MVP support:
- ASCII (``Values:``) — full,
- binary ``real`` (e.g. ``.tran`` with the ``real`` flag) — full,
- binary ``complex`` (e.g. ``.ac``) — values as (Re, Im) pairs; the
  first "variable" (the axis) is treated as real even though it is
  stored as complex with a zero imaginary part,
- ``fastaccess`` — raises ``UnsupportedRawFormat``,
- any other flag combination — raises ``UnsupportedRawFormat``.

Design notes:
- The header is decoded as UTF-16-LE first (LTspice on Windows writes
  binary ``.raw`` with a UTF-16-LE BOM); ASCII fallback is used otherwise.
- The first variable (``Variables: 0 ...``) is the independent axis
  (time/frequency). LTspice encodes the sign of the time variable as a
  "step rollover" marker, so we always ``abs()`` the axis.
- For a complex axis the imaginary part is conventionally zero, but we
  still return the magnitude for safety.
- No numpy / pandas — pure standard library.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal


class UnsupportedRawFormat(ValueError):
    """Raised when the ``.raw`` format is outside MVP support."""


Flag = Literal["real", "complex"]


@dataclass
class RawVariable:
    index: int
    name: str
    kind: str


@dataclass
class RawHeader:
    title: str = ""
    date: str = ""
    plotname: str = ""
    flags: list[str] = field(default_factory=list)
    n_variables: int = 0
    n_points: int = 0
    offset: float = 0.0
    command: str = ""
    variables: list[RawVariable] = field(default_factory=list)
    is_binary: bool = False
    is_complex: bool = False
    is_fastaccess: bool = False


@dataclass
class RawFile:
    header: RawHeader
    axis: list[float]
    traces: dict[str, list[float]]
    """Magnitude if ``complex``; direct value if ``real``."""
    traces_complex: dict[str, list[complex]] | None = None
    path: str | None = None

    @property
    def variable_names(self) -> list[str]:
        return [v.name for v in self.header.variables]

    @property
    def is_complex(self) -> bool:
        return self.header.is_complex


def _decode_header_bytes(raw_bytes: bytes) -> tuple[str, int]:
    """Decode the header to text and return (text, header_byte_length).

    The header ends with a ``Binary:`` or ``Values:`` line — we look for
    both in both encodings.
    """
    markers_utf16 = (
        ("Binary:\n", "utf-16-le"),
        ("Binary:\r\n", "utf-16-le"),
        ("Values:\n", "utf-16-le"),
        ("Values:\r\n", "utf-16-le"),
    )
    markers_ascii = (
        ("Binary:\n", "utf-8"),
        ("Binary:\r\n", "utf-8"),
        ("Values:\n", "utf-8"),
        ("Values:\r\n", "utf-8"),
    )
    for marker, enc in markers_utf16:
        encoded_marker = marker.encode(enc)
        idx = raw_bytes.find(encoded_marker)
        if idx >= 0:
            header_bytes = raw_bytes[: idx + len(encoded_marker)]
            try:
                offset = 2 if header_bytes.startswith(b"\xff\xfe") else 0
                text = header_bytes[offset:].decode(enc)
                # Consistency check — the header should start with "Title:".
                if "Title:" in text[:32]:
                    return text, idx + len(encoded_marker)
            except UnicodeDecodeError:
                continue
    for marker, enc in markers_ascii:
        encoded_marker = marker.encode(enc)
        idx = raw_bytes.find(encoded_marker)
        if idx >= 0:
            text = raw_bytes[: idx + len(encoded_marker)].decode(enc, errors="replace")
            return text, idx + len(encoded_marker)
    raise UnsupportedRawFormat(
        "Neither `Binary:` nor `Values:` marker found in .raw header."
    )


def _parse_header(text: str) -> RawHeader:
    header = RawHeader()
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        low = line.strip().lower()
        if low.startswith("title:"):
            header.title = line.split(":", 1)[1].strip()
        elif low.startswith("date:"):
            header.date = line.split(":", 1)[1].strip()
        elif low.startswith("plotname:"):
            header.plotname = line.split(":", 1)[1].strip()
        elif low.startswith("flags:"):
            flags = [t.strip().lower() for t in line.split(":", 1)[1].split() if t.strip()]
            header.flags = flags
            header.is_complex = "complex" in flags
            header.is_fastaccess = "fastaccess" in flags
        elif low.startswith("no. variables:"):
            header.n_variables = int(line.split(":", 1)[1].strip())
        elif low.startswith("no. points:"):
            header.n_points = int(line.split(":", 1)[1].strip())
        elif low.startswith("offset:"):
            try:
                header.offset = float(line.split(":", 1)[1].strip())
            except ValueError:
                header.offset = 0.0
        elif low.startswith("command:"):
            header.command = line.split(":", 1)[1].strip()
        elif low.startswith("variables:"):
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].strip().lower().startswith(("binary:", "values:")):
                parts = lines[i].split()
                if len(parts) >= 3:
                    header.variables.append(
                        RawVariable(index=int(parts[0]), name=parts[1], kind=parts[2])
                    )
                i += 1
            continue
        elif low.startswith("binary:"):
            header.is_binary = True
            break
        elif low.startswith("values:"):
            header.is_binary = False
            break
        i += 1
    return header


def _resolve_n_points(body_len: int, record_bytes: int, declared: int) -> int:
    # LTspice can over-report `No. Points` in the header when `.step` interacts
    # with adaptive timestepping — the declared count is an upper bound, the
    # actual point count must be derived from the body byte length. Trust the
    # smaller of the two.
    if record_bytes <= 0 or declared <= 0:
        raise UnsupportedRawFormat(
            f".raw has invalid layout: record_bytes={record_bytes}, declared_points={declared}."
        )
    actual = body_len // record_bytes
    if actual <= 0:
        raise UnsupportedRawFormat(
            f".raw body too short for one record: body={body_len} B, record={record_bytes} B."
        )
    return min(actual, declared)


def _axis_monotonic_score(body: bytes, record_bytes: int, sample: int = 64) -> float:
    """How sane the time axis looks when the body is read at ``record_bytes``
    stride: the fraction of the first ``sample`` records whose 8-byte axis
    double is finite and non-decreasing in magnitude. The *true* stride yields
    a clean ramp (≈1.0); a wrong stride reads data bytes as the axis and scores
    low (NaN / denormal / non-monotonic). Returns -1.0 when too few records fit.
    """
    n = min(len(body) // record_bytes, sample)
    if n < 2:
        return -1.0
    ok = total = 0
    prev: float | None = None
    for i in range(n):
        (val,) = struct.unpack_from("<d", body, i * record_bytes)
        if not math.isfinite(val):
            total += 1          # a non-finite axis value is a wrong-stride tell
            prev = None
            continue
        a = abs(val)            # LTspice marks step rollover in the time sign
        if prev is not None:
            total += 1
            if a >= prev:
                ok += 1
        prev = a
    return ok / total if total else 0.0


def _pick_real_layout(body: bytes, n_vars: int, declared_points: int) -> tuple[int, bool]:
    """Pick the record layout for a ``real`` binary ``.raw``: ``(record_bytes,
    compressed)``.

    Modern LTspice (≥ XVII / 26.x) emits "compressed" records — the independent
    axis is a double (8 B) but the other variables are floats (4 B); legacy
    LTspice used all doubles. The header flags don't distinguish them.

    We pick by *correctness*: decode the time axis under each candidate stride
    and keep the one that looks like a real axis (finite + monotonic). A wrong
    stride reads data bytes as the axis and produces garbage. This is robust to
    a trailing *partial* record (an interrupted / adaptive-step run), which used
    to defeat the older "whichever size divides the body more cleanly" heuristic
    and silently mis-stride the whole file. Declared ``No. Points`` and the
    cleaner division are fallback tiebreakers when the axis can't decide.
    """
    body_len = len(body)
    record_full = 8 * n_vars
    record_compressed = 8 + 4 * (n_vars - 1) if n_vars >= 1 else 0
    if record_full <= 0:
        raise UnsupportedRawFormat(f".raw has invalid n_vars={n_vars}.")

    # n_vars == 1 collapses both layouts (no data variables besides the axis).
    if record_compressed == record_full or record_compressed <= 0:
        return record_full, False

    score_comp = _axis_monotonic_score(body, record_compressed)
    score_full = _axis_monotonic_score(body, record_full)
    if abs(score_comp - score_full) > 1e-9:
        return (record_compressed, True) if score_comp > score_full else (record_full, False)

    # Axis sanity tied → the layout whose implied point count is closest to the
    # declared count, then the cleaner division (compressed preferred on a tie).
    if declared_points > 0:
        d_comp = abs(body_len // record_compressed - declared_points)
        d_full = abs(body_len // record_full - declared_points)
        if d_comp != d_full:
            return (record_compressed, True) if d_comp < d_full else (record_full, False)
    if body_len % record_compressed <= body_len % record_full:
        return record_compressed, True
    return record_full, False


def _parse_ascii_values(
    text: str, header: RawHeader
) -> tuple[list[float], dict[str, list[float]], dict[str, list[complex]] | None]:
    lines = text.splitlines()
    # Skip to `Values:`.
    start = 0
    for idx, ln in enumerate(lines):
        if ln.strip().lower().startswith("values:"):
            start = idx + 1
            break
    axis: list[float] = []
    cols: list[list[float]] = [[] for _ in header.variables]
    pos = start
    while pos < len(lines) and len(axis) < header.n_points:
        head = lines[pos].strip()
        if not head:
            pos += 1
            continue
        parts = head.split()
        # LTspice writes complex ASCII as `re,im`. MVP does not support this
        # path — flag as unsupported and ask for a binary export instead.
        if header.is_complex:
            raise UnsupportedRawFormat(
                "ASCII complex .raw is not supported in MVP — please save as binary."
            )
        # First line of a point: "<idx>\t<axis-value>".
        try:
            _ = int(parts[0])
            axis_val = float(parts[1])
        except (ValueError, IndexError):
            pos += 1
            continue
        axis.append(abs(axis_val))
        cols[0].append(abs(axis_val))
        pos += 1
        for col_idx in range(1, header.n_variables):
            if pos >= len(lines):
                raise UnsupportedRawFormat("Unexpected end of ASCII .raw file.")
            try:
                cols[col_idx].append(float(lines[pos].strip()))
            except ValueError as exc:
                raise UnsupportedRawFormat(f"Unparseable value: {lines[pos]!r}") from exc
            pos += 1
    traces = {var.name: cols[i] for i, var in enumerate(header.variables)}
    return axis, traces, None


def _parse_binary_values(
    raw_bytes: bytes,
    header: RawHeader,
    body_offset: int,
) -> tuple[list[float], dict[str, list[float]], dict[str, list[complex]] | None]:
    if header.is_fastaccess:
        raise UnsupportedRawFormat("`fastaccess` flag is not supported in MVP.")

    body = raw_bytes[body_offset:]
    n_vars = header.n_variables
    n_points = header.n_points

    if header.is_complex:
        record_bytes = 16 * n_vars
        n_points = _resolve_n_points(len(body), record_bytes, n_points)
        header.n_points = n_points
        cols: list[list[float]] = [[] for _ in range(n_vars)]
        cols_complex: list[list[complex]] = [[] for _ in range(n_vars)]
        fmt = "<" + "d" * (2 * n_vars)
        struct_size = struct.calcsize(fmt)
        for p in range(n_points):
            chunk = body[p * struct_size : (p + 1) * struct_size]
            values = struct.unpack(fmt, chunk)
            for v in range(n_vars):
                re = values[2 * v]
                im = values[2 * v + 1]
                c = complex(re, im)
                cols_complex[v].append(c)
                cols[v].append(abs(c))
        axis = [abs(c) for c in cols_complex[0]]
        traces = {var.name: cols[i] for i, var in enumerate(header.variables)}
        traces_complex = {var.name: cols_complex[i] for i, var in enumerate(header.variables)}
        return axis, traces, traces_complex

    record_bytes, compressed = _pick_real_layout(body, n_vars, n_points)
    n_points = _resolve_n_points(len(body), record_bytes, n_points)
    header.n_points = n_points
    cols = [[] for _ in range(n_vars)]
    if compressed:
        # 8 B double for the axis, 4 B float for every other variable.
        data_fmt = "<d" + "f" * (n_vars - 1)
    else:
        data_fmt = "<" + "d" * n_vars
    struct_size = struct.calcsize(data_fmt)
    assert struct_size == record_bytes, (struct_size, record_bytes)
    for p in range(n_points):
        chunk = body[p * struct_size : (p + 1) * struct_size]
        values = struct.unpack(data_fmt, chunk)
        for v in range(n_vars):
            cols[v].append(values[v])
    # LTspice encodes the time sign as a step-rollover marker; take abs().
    axis = [abs(x) for x in cols[0]]
    cols[0] = list(axis)
    traces = {var.name: cols[i] for i, var in enumerate(header.variables)}
    return axis, traces, None


def parse_raw(source: str | Path) -> RawFile:
    """Read an LTspice ``.raw`` file."""
    path = Path(source)
    raw_bytes = path.read_bytes()
    header_text, header_len = _decode_header_bytes(raw_bytes)
    header = _parse_header(header_text)

    if header.n_variables <= 0 or header.n_points <= 0:
        raise UnsupportedRawFormat(".raw file has no variables or no points.")

    if header.is_binary:
        axis, traces, traces_complex = _parse_binary_values(raw_bytes, header, header_len)
    else:
        # ASCII — the body is text too. Decode the whole file once.
        try:
            text_full = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text_full = raw_bytes.decode("latin-1", errors="replace")
        axis, traces, traces_complex = _parse_ascii_values(text_full, header)

    return RawFile(
        header=header,
        axis=axis,
        traces=traces,
        traces_complex=traces_complex,
        path=str(path),
    )


def step_segment_bounds(axis) -> list[tuple[int, int]]:
    """``(start, end)`` index ranges of each ``.step`` section in a (possibly
    stepped) ``.raw`` axis.

    A ``.step`` run (e.g. the parasitic ``sweep_corner`` corner sweep) is
    concatenated by LTspice into one data block, resetting the time axis to
    ~0 at each boundary — it flags the rollover by negating the time sample,
    which :func:`parse_raw` already ``abs()``-es away. We recover the
    boundaries by detecting where the (monotonic-within-a-step) axis
    decreases. A non-stepped axis returns a single ``(0, len)`` segment.
    """
    n = len(axis)
    if n == 0:
        return []
    bounds: list[tuple[int, int]] = []
    start = 0
    for i in range(1, n):
        if axis[i] < axis[i - 1]:
            bounds.append((start, i))
            start = i
    bounds.append((start, n))
    return bounds


def primary_step_range(axis) -> tuple[int, int]:
    """``(start, end)`` of the representative step to display/analyse.

    The corner sweep convention is ``0=min, 1=typ, 2=max`` (``composer``),
    so the **middle** segment is the typ corner; this generalises to
    ``n // 2`` for any step count and returns the whole axis when the run is
    not stepped. Returns ``(0, 0)`` for an empty axis.
    """
    bounds = step_segment_bounds(axis)
    if not bounds:
        return (0, 0)
    return bounds[len(bounds) // 2]


def list_traces(source: str | Path) -> list[str]:
    """Light variant — read the header only and return variable names."""
    raw_bytes = Path(source).read_bytes()
    header_text, _ = _decode_header_bytes(raw_bytes)
    header = _parse_header(header_text)
    return [v.name for v in header.variables]


def extract_to_csv(
    raw: RawFile,
    traces: Iterable[str],
    csv_path: str | Path,
    *,
    axis_name: str | None = None,
) -> Path:
    """Write selected traces (axis + traces) to a CSV file."""
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(traces)
    missing = [t for t in cols if t not in raw.traces]
    if missing:
        raise KeyError(f"Missing traces in .raw: {missing}")
    axis_label = axis_name or (raw.variable_names[0] if raw.variable_names else "axis")
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(",".join([axis_label, *cols]) + "\n")
        for i, ax in enumerate(raw.axis):
            row = [f"{ax:.9g}"]
            for c in cols:
                row.append(f"{raw.traces[c][i]:.9g}")
            fh.write(",".join(row) + "\n")
    return csv_path
