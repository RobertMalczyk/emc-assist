"""``.raw`` waveform inspection / export — service layer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from emc_assistant.results import UnsupportedRawFormat, extract_to_csv, parse_raw
from emc_assistant.results.raw_parser import primary_step_range, step_segment_bounds
from emc_assistant.results.detectors import (
    CISPR_BAND_B,
    VERDICT_SKIP_FRACTION,
    VERDICT_SWEEP_POINTS,
    ReceiverReading,
    ReceiverSweep,
    receiver_quasi_peak,
    receiver_sweep,
)
from emc_assistant.results.limits import (
    STANDARDS,
    WorstMargin,
    get_standard,
    limit_dbuv,
    margin_db,
    worst_margin,
)
from emc_assistant.results.metrics import pick_default_trace
from emc_assistant.service.results import ServiceError

# Bump when the cached payload shape changes, so stale caches are recomputed
# rather than served. v3 = step-aware (single typ corner) waveform/spectrum.
_WAVEFORM_SCHEMA = 3
_SPECTRUM_SCHEMA = 3


@dataclass
class RawTrace:
    index: int
    name: str
    kind: str


@dataclass
class RawInspectResult:
    title: str
    plotname: str
    flags: list[str]
    n_variables: int
    n_points: int
    axis_min: float | None
    axis_max: float | None
    traces: list[RawTrace]


@dataclass
class RawExportResult:
    output_path: Path
    traces: list[str]


def _load_raw(path: Path):
    if not path.is_file():
        raise ServiceError(f"File not found: {path}")
    try:
        return parse_raw(path)
    except UnsupportedRawFormat as exc:
        raise ServiceError(f"Unsupported .raw format: {exc}", exit_code=2) from exc


def inspect_raw(raw_path: str | Path) -> RawInspectResult:
    """Parse a ``.raw`` file and return its header + trace list."""
    raw = _load_raw(Path(raw_path))
    h = raw.header
    return RawInspectResult(
        title=h.title,
        plotname=h.plotname,
        flags=list(h.flags),
        n_variables=h.n_variables,
        n_points=h.n_points,
        axis_min=min(raw.axis) if raw.axis else None,
        axis_max=max(raw.axis) if raw.axis else None,
        traces=[RawTrace(v.index, v.name, v.kind) for v in h.variables],
    )


def export_raw_csv(
    raw_path: str | Path,
    traces: list[str],
    output_path: str | Path,
) -> RawExportResult:
    """Export selected traces of a ``.raw`` file to CSV. An empty
    ``traces`` list exports every trace except the axis."""
    raw = _load_raw(Path(raw_path))
    requested = list(traces) or list(raw.variable_names[1:])
    out = Path(output_path)
    extract_to_csv(raw, requested, out)
    return RawExportResult(output_path=out, traces=requested)


@dataclass
class QuasiPeakReport:
    """Result of a Mode 2 (receiver-like) quasi-peak run on a ``.raw`` file,
    with the margin against a compliance standard."""

    trace: str
    reading: ReceiverReading
    standard_name: str | None = None
    quasi_peak_margin_db: float | None = None
    average_margin_db: float | None = None


def _require_standard(standard_id: str | None):
    standard = get_standard(standard_id)
    if standard is None:
        raise ServiceError(
            f"Unknown compliance standard {standard_id!r}. "
            f"Available: {', '.join(sorted(STANDARDS))}"
        )
    return standard


def _resolve_trace(raw, trace: str | None):
    """Pick the voltage trace to analyse — the named one, or the heuristic
    default. Returns ``(name, values)`` or raises :class:`ServiceError`."""
    name = trace or pick_default_trace(raw)
    if name is None:
        raise ServiceError("No voltage trace found in the .raw file.")
    values = raw.traces.get(name)
    if values is None:  # case-insensitive retry
        by_lower = {k.lower(): k for k in raw.traces}
        values = raw.traces.get(by_lower.get(name.lower(), ""))
    if not values:
        available = ", ".join(raw.variable_names[1:9])
        raise ServiceError(
            f"Trace {name!r} not found in the .raw file. "
            f"Available: {available} …"
        )
    return name, values


def quasi_peak(
    raw_path: str | Path,
    *,
    center_hz: float,
    trace: str | None = None,
    skip_fraction: float = 0.0,
    standard_id: str | None = None,
) -> QuasiPeakReport:
    """Mode 2 — a receiver-like quasi-peak estimate at one centre
    frequency, computed from a ``.raw`` file (concept note §7), with the
    margin against a compliance standard (default: EN 55022 Class B).

    A CISPR-like pre-compliance diagnostic — never a compliance verdict.
    ``trace`` defaults to the heuristic default voltage trace.
    """
    standard = _require_standard(standard_id)
    raw = _load_raw(Path(raw_path))
    name, values = _resolve_trace(raw, trace)
    # A stepped .raw (corner sweep) concatenates several transients; analyse
    # only the representative (typ) step, never the wrapped concatenation.
    i0, i1 = primary_step_range(raw.axis)
    reading = receiver_quasi_peak(
        raw.axis[i0:i1], values[i0:i1], float(center_hz), CISPR_BAND_B,
        skip_fraction=skip_fraction,
    )
    qp_margin = avg_margin = None
    if reading.usable:
        qp_margin = margin_db(
            reading.quasi_peak_dbuv, standard.quasi_peak, float(center_hz)
        )
        avg_margin = margin_db(
            reading.average_dbuv, standard.average, float(center_hz)
        )
    return QuasiPeakReport(
        trace=name,
        reading=reading,
        standard_name=standard.name,
        quasi_peak_margin_db=qp_margin,
        average_margin_db=avg_margin,
    )


@dataclass
class QuasiPeakSweepReport:
    """Result of a Mode 3 (receiver-like sweep) run on a ``.raw`` file,
    with the worst margin across the band vs a compliance standard."""

    trace: str
    sweep: ReceiverSweep
    standard_name: str | None = None
    quasi_peak_worst: WorstMargin | None = None
    average_worst: WorstMargin | None = None
    n_steps: int = 1


def quasi_peak_sweep(
    raw_path: str | Path,
    *,
    trace: str | None = None,
    skip_fraction: float = VERDICT_SKIP_FRACTION,
    standard_id: str | None = None,
    n_points: int = VERDICT_SWEEP_POINTS,
) -> QuasiPeakSweepReport:
    """Mode 3 — a receiver-like sweep across CISPR Band B from a ``.raw``
    file (concept note §7): the Mode 2 chain at every swept frequency,
    plus the worst margin vs a compliance standard (default EN 55022
    Class B).

    A CISPR-like pre-compliance diagnostic — never a compliance verdict.
    """
    standard = _require_standard(standard_id)
    raw = _load_raw(Path(raw_path))
    name, values = _resolve_trace(raw, trace)
    # A stepped .raw (corner sweep) concatenates several transients into one
    # block; the FFT/detectors must run on a single transient, so restrict to
    # the representative (typ) step rather than the wrapped concatenation.
    bounds = step_segment_bounds(raw.axis)
    i0, i1 = bounds[len(bounds) // 2] if bounds else (0, len(raw.axis))
    sweep = receiver_sweep(
        raw.axis[i0:i1], values[i0:i1], CISPR_BAND_B,
        n_points=n_points, skip_fraction=skip_fraction,
    )
    qp_worst = avg_worst = None
    if sweep.usable:
        qp_worst = worst_margin(
            sweep.freq_hz, sweep.quasi_peak_dbuv, standard.quasi_peak
        )
        avg_worst = worst_margin(
            sweep.freq_hz, sweep.average_dbuv, standard.average
        )
    return QuasiPeakSweepReport(
        trace=name,
        sweep=sweep,
        standard_name=standard.name,
        quasi_peak_worst=qp_worst,
        average_worst=avg_worst,
        n_steps=len(bounds),
    )


def load_spectrum(project_root, *, n_points: int = 96, standard_id: str | None = None) -> dict:
    """Detector-vs-limit spectrum for the Results screen: the Mode-3 sweep
    (peak / quasi-peak / average dBµV per frequency) over ``generated/
    testbench.raw`` plus the compliance limit curves — i.e. the very curves
    the worst-margin numbers are read off.

    The sweep is expensive over a large ``.raw``, so the result is cached to
    ``results/spectrum.json`` and reused while it is newer than the ``.raw``.
    Returns ``{"available": False, "note": …}`` before a local-run.
    """
    from emc_assistant.service.project import require_project

    _config, layout = require_project(project_root)
    raw_path = layout.generated_dir / "testbench.raw"
    cache = layout.results_dir / "spectrum.json"
    if not raw_path.is_file():
        return {"available": False, "note": "no testbench.raw — run in local-run mode"}
    if cache.is_file() and cache.stat().st_mtime >= raw_path.stat().st_mtime:
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if cached.get("schema") == _SPECTRUM_SCHEMA:
                return cached
        except (OSError, json.JSONDecodeError):
            pass

    rep = quasi_peak_sweep(raw_path, standard_id=standard_id, n_points=n_points)
    sweep = rep.sweep
    if not sweep.usable:
        return {"available": False, "note": sweep.note or "sweep not usable (timestep too coarse for CISPR band B?)"}
    std = _require_standard(standard_id)
    freqs = [float(x) for x in sweep.freq_hz]
    qp = [float(x) for x in sweep.quasi_peak_dbuv]
    avg = [float(x) for x in sweep.average_dbuv]
    peak = [float(x) for x in sweep.peak_dbuv]
    points = [
        {
            "hz": f,
            "peak": peak[i] if i < len(peak) else None,
            "qp": qp[i],
            "avg": avg[i],
            "qp_limit": limit_dbuv(std.quasi_peak, f),
            "avg_limit": limit_dbuv(std.average, f),
        }
        for i, f in enumerate(freqs)
    ]
    wqp, wavg = rep.quasi_peak_worst, rep.average_worst
    out = {
        "available": True,
        "schema": _SPECTRUM_SCHEMA,
        "standard_name": rep.standard_name or "",
        "trace": rep.trace,
        "n_points": len(points),
        "n_steps": rep.n_steps,
        "corner": "typ" if rep.n_steps > 1 else None,
        "points": points,
        "worst_qp": {"margin_db": wqp.margin_db, "hz": wqp.freq_hz} if wqp else None,
        "worst_avg": {"margin_db": wavg.margin_db, "hz": wavg.freq_hz} if wavg else None,
    }
    try:
        layout.results_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out), encoding="utf-8")
    except OSError:
        pass
    return out


_UNIT_BY_KIND = {"voltage": "V", "device_current": "A", "subckt_current": "A", "current": "A"}


def _safe_cache_name(trace: str | None) -> str:
    """Per-trace cache filename. ``None`` (the primary voltage) keeps the
    historic ``waveform.json``; a named trace gets ``waveform_<safe>.json``."""
    if not trace:
        return "waveform.json"
    safe = "".join(ch if ch.isalnum() else "_" for ch in trace.lower()).strip("_")
    return f"waveform_{safe or 'trace'}.json"


def load_waveform(project_root, *, max_buckets: int = 1500, trace: str | None = None) -> dict:
    """The time-domain envelope of a ``.raw`` trace, for the Results-screen
    waveform analyzer. A transient ``.raw`` has up to ~1e6 points, so this
    returns a **min/max envelope** down to ``max_buckets`` buckets — naive
    decimation would alias away the switching spikes, the min/max band keeps
    them. ``trace`` None resolves the measured voltage (``V(meas)``); pass a
    name for the comparison subplot. Every trace shares the axis length and
    bucket edges, so two envelopes line up sample-for-sample on the time
    axis. Cached per trace (newer-than-raw reuse)."""
    import numpy as np

    from emc_assistant.service.project import require_project

    _config, layout = require_project(project_root)
    raw_path = layout.generated_dir / "testbench.raw"
    cache = layout.results_dir / _safe_cache_name(trace)
    if not raw_path.is_file():
        return {"available": False, "note": "no testbench.raw — run in local-run mode"}
    if cache.is_file() and cache.stat().st_mtime >= raw_path.stat().st_mtime:
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            # Recompute stale-schema caches (pre-M2.18 kind/unit, pre-step-aware).
            if not cached.get("available") or cached.get("schema") == _WAVEFORM_SCHEMA:
                return cached
        except (OSError, json.JSONDecodeError):
            pass

    raw = _load_raw(raw_path)
    try:
        name, values = _resolve_trace(raw, trace)
    except ServiceError as exc:
        return {"available": False, "note": str(exc)}
    kind = next((v.kind for v in raw.header.variables if v.name == name), "")
    # A stepped .raw (corner sweep) concatenates one transient per corner and
    # resets the time axis at each boundary; show only the representative (typ)
    # step, otherwise the envelope wraps from the right edge back to the left.
    bounds = step_segment_bounds(raw.axis)
    n_steps = len(bounds)
    i0, i1 = bounds[len(bounds) // 2] if bounds else (0, len(raw.axis))
    ax = np.asarray(raw.axis[i0:i1], dtype=float)
    vals = np.asarray(values[i0:i1], dtype=float)
    n = int(min(len(ax), len(vals)))
    if n == 0:
        return {"available": False, "note": "trace is empty"}
    buckets = int(min(max_buckets, n))
    edges = np.linspace(0, n, buckets + 1, dtype=int)
    points = []
    for b in range(buckets):
        i0, i1 = int(edges[b]), int(edges[b + 1])
        if i1 <= i0:
            i1 = i0 + 1
        seg = vals[i0:i1]
        points.append({
            "t": float(ax[i0]),
            "lo": float(seg.min()),
            "hi": float(seg.max()),
        })
    out = {
        "available": True,
        "schema": _WAVEFORM_SCHEMA,
        "trace": name,
        "kind": kind,
        "unit": _UNIT_BY_KIND.get(kind.lower(), ""),
        "n_raw": n,
        "n_steps": n_steps,
        "corner": "typ" if n_steps > 1 else None,
        "t_min": float(ax[0]),
        "t_max": float(ax[-1]),
        "points": points,
    }
    try:
        layout.results_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out), encoding="utf-8")
    except OSError:
        pass
    return out
