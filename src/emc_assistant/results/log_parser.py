"""LTspice ``.log`` parser.

MVP extracts:
- warnings and errors,
- ``.meas`` results in all forms LTspice emits:
    * single-line ``name: value`` / ``name=value``,
    * single-line ``name: MAX(v(...))=value FROM t1 TO t2``,
    * multi-line ``Measurement: name`` block (optionally with
      ``step  MAX(...)`` header and one row per ``.step`` corner),
- total simulation time ("Total elapsed time"),
- ``.step`` count when visible,
- a simple ``pass|fail|unknown`` status.

For ``.step``-aware measurements we keep the **last** value as the
canonical metric and also expose each per-step value as
``<name>_step<N>`` for downstream inspection.

The full ``.raw`` parser lives in ``raw_parser.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LogSummary:
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    measurements: dict[str, float] = field(default_factory=dict)
    total_time_seconds: float | None = None
    step_count: int | None = None
    status: str = "unknown"
    raw_path: str | None = None

    def has_errors(self) -> bool:
        return bool(self.errors)


_TIME_LINE = re.compile(r"total elapsed time[^0-9]*([0-9.]+)\s*seconds", re.IGNORECASE)
_STEP_LINE = re.compile(r"^\.step\s", re.IGNORECASE)
_MEASUREMENT_HEADER = re.compile(r"^\s*Measurement:\s*([A-Za-z_]\w*)\s*$", re.IGNORECASE)
_MEAS_TABLE_HEADER = re.compile(r"^\s*step\b", re.IGNORECASE)

# Single-line `name: value` or `name = value` (value may be followed by `FROM ...`).
_MEAS_SIMPLE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
    r"(?:\s+(?:FROM|AT|from|at)\b.*)?\s*$"
)

# Single-line `name: SOMETHING(...)=value FROM ...`.
# `.+?` (lazy) supports nested parens like `MAX(v(meas))`.
_MEAS_FUNC = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*\w+\(.+?\)\s*=\s*"
    r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
)

# Inside a Measurement: block, the data lines:
#   "<step_idx>\t<value>"     (sweep result table)
#   "<value>"                 (single-run result with no header)
#   "MAX(v(...))=<value> FROM ..."  (legacy line form)
_BLOCK_DATA_ROW = re.compile(
    r"^\s*\d+\s+([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*$"
)
_BLOCK_LONE_VALUE = re.compile(
    r"^\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*$"
)
_BLOCK_FUNC_EQUALS = re.compile(
    r".*=\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
    r"(?:\s+(?:FROM|AT|from|at)\b.*)?\s*$"
)


def _try_float(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _record_measurement(summary: LogSummary, name: str, values: list[float]) -> None:
    if not values:
        return
    if len(values) == 1:
        summary.measurements[name] = values[0]
        return
    # Step sweep: keep the last value as canonical; expose per-step entries.
    summary.measurements[name] = values[-1]
    for idx, v in enumerate(values, start=1):
        summary.measurements[f"{name}_step{idx}"] = v


def parse_log(source: str | Path) -> LogSummary:
    if isinstance(source, Path):
        text = source.read_text(encoding="utf-8", errors="replace")
        raw_path: str | None = str(source)
    else:
        text = str(source)
        raw_path = None

    summary = LogSummary(raw_path=raw_path)
    step_seen = 0

    block_name: str | None = None
    block_values: list[float] = []

    def close_block() -> None:
        nonlocal block_name, block_values
        if block_name is not None:
            _record_measurement(summary, block_name, block_values)
        block_name = None
        block_values = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        low = line.strip().lower()

        if not line.strip():
            close_block()
            continue

        if low.startswith("warning"):
            close_block()
            summary.warnings.append(line.strip())
            continue
        if low.startswith("error") or "fatal" in low:
            close_block()
            summary.errors.append(line.strip())
            continue

        m_time = _TIME_LINE.search(line)
        if m_time:
            close_block()
            v = _try_float(m_time.group(1))
            if v is not None:
                summary.total_time_seconds = v
            continue

        if _STEP_LINE.match(low):
            step_seen += 1
            continue

        m_header = _MEASUREMENT_HEADER.match(line)
        if m_header:
            close_block()
            block_name = m_header.group(1)
            block_values = []
            continue

        # Inside a Measurement: block.
        if block_name is not None:
            if _MEAS_TABLE_HEADER.match(line):
                continue  # column header row like "step  MAX(v(meas))"
            m_row = _BLOCK_DATA_ROW.match(line)
            if m_row:
                v = _try_float(m_row.group(1))
                if v is not None:
                    block_values.append(v)
                continue
            m_fn = _BLOCK_FUNC_EQUALS.match(line)
            if m_fn:
                v = _try_float(m_fn.group(1))
                if v is not None:
                    block_values.append(v)
                continue
            m_lone = _BLOCK_LONE_VALUE.match(line)
            if m_lone:
                v = _try_float(m_lone.group(1))
                if v is not None:
                    block_values.append(v)
                continue
            # Anything unrecognised inside a block ends it.
            close_block()
            # Fall through so single-line forms below can match.

        m_func = _MEAS_FUNC.match(line)
        if m_func:
            v = _try_float(m_func.group(2))
            if v is not None:
                summary.measurements[m_func.group(1)] = v
            continue

        m_simple = _MEAS_SIMPLE.match(line)
        if m_simple:
            v = _try_float(m_simple.group(2))
            if v is not None:
                summary.measurements[m_simple.group(1)] = v
            continue

    close_block()

    if step_seen:
        summary.step_count = step_seen

    if summary.errors:
        summary.status = "fail"
    elif summary.total_time_seconds is not None or summary.measurements:
        summary.status = "pass"
    else:
        summary.status = "unknown"

    return summary
